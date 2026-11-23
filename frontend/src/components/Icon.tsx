const paths: Record<string, string[]> = {
  sparkle: ["M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"],
  documents: ["M7 3h8l4 4v14H7V3Z", "M15 3v5h4", "M10 12h6M10 16h6", "M4 7v14"],
  people: [
    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",
    "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
    "M17 4a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.87",
  ],
  activity: ["M3 3v18h18", "M7 14l4-5 4 3 6-8"],
  plus: ["M12 5v14M5 12h14"],
  arrow: ["M7 17 17 7M7 7h10v10"],
  logout: ["M9 4H4v16h5M13 8l4 4-4 4M8 12h13"],
  close: ["m6 6 12 12M6 18 18 6"],
  chevron: ["m6 9 6 6 6-6"],
  upload: ["M12 16V3M7 8l5-5 5 5M4 16v5h16v-5"],
  lock: ["M5 11h14v10H5V11ZM8 11V7a4 4 0 0 1 8 0v4"],
};

export default function Icon({
  name,
  className = "",
}: {
  name: string;
  className?: string;
}) {
  return (
    <svg
      className={`icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {(paths[name] || paths.sparkle).map((d, i) => (
        <path key={i} d={d} />
      ))}
    </svg>
  );
}
