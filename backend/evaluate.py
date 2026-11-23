"""Run a reproducible quality/latency experiment, then prepare a human review sheet.

Uses an isolated dataset under runtime/evaluations; never modifies uploaded user docs.
Live mode makes paid API requests. Fake mode is only a pipeline smoke test.
"""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from .auth import create_user
from .config import ROOT, Settings
from .db import now, uid
from .documents import extract
from .errors import AppError
from .service import Service

NEGATIVES = ['What is the weather in Tokyo tomorrow?', 'Who won the 1986 football World Cup?',
             'What is the cafeteria menu this Friday?', 'What is our company revenue this year?',
             'What is the office Wi-Fi password?']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fake', action='store_true', help='Offline smoke test; not a semantic quality measurement')
    parser.add_argument('--review', type=Path, help='Summarize a completed review.csv instead of calling AI')
    args = parser.parse_args()
    if args.review:
        with args.review.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        for field in ('retrieval_at_3_correct', 'reference_correct', 'snippet_supports_answer'):
            values = [r[field].strip().lower() for r in rows if r[field].strip().lower() in ('yes', 'no')]
            print(f'{field}: {values.count("yes")}/{len(values)} reviewed' + (f' ({100*values.count("yes")/len(values):.1f}%)' if values else ''))
        return
    settings = Settings()
    if not args.fake and not settings.api_key:
        parser.error(f'Set {settings.key_variable} in .env before live evaluation, or use --fake for an offline smoke test.')
    if args.fake:
        settings.provider = 'fake'
    elif settings.provider == 'fake':
        parser.error('Choose gemini or openai in GUIDELY_PROVIDER for a live evaluation, or pass --fake.')
    settings.data_dir = settings.data_dir / 'evaluations' / uid()
    service = Service(settings)
    user = create_user(service.db, 'evaluator', uid(), 'admin')
    service.start()
    try:
        index_started = time.perf_counter()
        for path in sorted((ROOT / 'data' / 'sample-docs').glob('*.md')):
            doc_id = uid()
            content = path.read_bytes()
            (service.uploads / doc_id).write_bytes(content)
            service.db.execute('INSERT INTO documents(id,filename,text,state,created_at) VALUES (?,?,?,?,?)',
                               (doc_id, path.name, extract(path.name, content), 'pending', now()))
            service.enqueue(doc_id)
        service.jobs.join()
        failed = service.db.all("SELECT * FROM jobs WHERE state='failed'")
        if failed:
            raise RuntimeError('Sample indexing failed: ' + failed[0]['error'])
        indexing_ms = (time.perf_counter()-index_started)*1000
        questions = json.loads((ROOT / 'data' / 'evaluation.json').read_text(encoding='utf-8'))
        review_rows, raw = [], []
        for item in questions:
            try:
                answer = service.ask(user, item['question'])
                error = ''
            except AppError as exc:
                service.db.count('error:' + exc.code)
                answer = {'answer': '', 'passages': [], 'references': []}
                error = exc.code
            top3 = answer['passages'][:3]
            match = any(p['filename'] == item['filename'] and item['expected'].lower() in p['snippet'].lower() for p in top3)
            raw.append({**item, 'result': answer, 'error': error, 'expected_passage_in_top3': match})
            review_rows.append({'question': item['question'], 'expected_file': item['filename'], 'expected_section': item['section'],
                                'expected_text': item['expected'], 'automatic_top3_match': match,
                                'answer': answer['answer'], 'sources': json.dumps(answer['references'], ensure_ascii=False),
                                'top3': json.dumps(top3, ensure_ascii=False), 'error': error,
                                'retrieval_at_3_correct': '', 'reference_correct': '', 'snippet_supports_answer': ''})
        # Warm question-embedding cache; do not cache generated answers or hide model latency.
        before = service.metrics()['counters']
        warm_times = []
        for item in questions[:5]:
            start = time.perf_counter()
            try:
                service.ask(user, item['question'])
            except AppError:
                continue
            warm_times.append((time.perf_counter()-start)*1000)
        after = service.metrics()['counters']
        # Capture score distributions to select an evidence-based relevance threshold.
        configured = settings.min_similarity
        settings.min_similarity = -1
        positive_candidates = []
        for item in questions:
            positive_candidates.append((item, service.search(item['question'])))
        negative_candidates = [(q, service.search(q)) for q in NEGATIVES]
        sweep = []
        for threshold in (0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60):
            correct = sum(any(p['score'] >= threshold and p['filename'] == item['filename'] and item['expected'].lower() in p['snippet'].lower() for p in passages[:3]) for item, passages in positive_candidates)
            rejected = sum(not any(p['score'] >= threshold for p in passages) for _, passages in negative_candidates)
            sweep.append({'threshold': threshold, 'retrieval_at_3': correct/len(questions), 'negative_rejection': rejected/len(NEGATIVES)})
        feasible = [s for s in sweep if s['retrieval_at_3'] >= .8]
        recommended = max(feasible, key=lambda s: (s['negative_rejection'], s['threshold']))['threshold'] if feasible else None
        settings.min_similarity = configured
        report = {'timestamp': now(), 'provider': settings.provider, 'embedding_model': settings.embedding_model,
                  'chat_model': settings.chat_model, 'quality_measurement_valid': not args.fake,
                  'indexing_ms': indexing_ms, 'metrics': service.metrics(),
                  'automatic_retrieval_at_3': sum(r['expected_passage_in_top3'] for r in raw)/len(raw),
                  'warm_cache_sample_size': len(warm_times),
                  'warm_cache_median_ms': statistics.median(warm_times) if warm_times else None,
                  'warm_cache_p95_ms': sorted(warm_times)[-1] if warm_times else None,
                  'repeated_question_cache_hits': after.get('question_cache_hits', 0)-before.get('question_cache_hits', 0),
                  'document_embeddings_during_repeat': after.get('document_embeddings_generated', 0)-before.get('document_embeddings_generated', 0),
                  'configured_threshold': configured, 'suggested_threshold': recommended, 'threshold_sweep': sweep,
                  'negative_candidates': negative_candidates, 'results': raw,
                  'manual_review': 'Fill yes/no in review.csv, then run --review <path>. Never count automatic text matches as human validation.'}
        output = settings.data_dir
        (output / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        with (output / 'review.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(review_rows[0])); writer.writeheader(); writer.writerows(review_rows)
        print(f'Results: {output / "report.json"}\nHuman review: {output / "review.csv"}')
        print('OFFLINE SMOKE TEST ONLY' if args.fake else 'Live evaluation complete. Human review is still required.')
    finally:
        service.stop()


if __name__ == '__main__':
    main()
