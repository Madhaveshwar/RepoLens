import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Simple, clean pagination: "Showing 1–10 of 47  [Prev] 1 2 3 4 5 [Next]".
 * Purely presentational — the caller keeps page state so filters/sorting are
 * preserved automatically when the page changes.
 */

interface PaginationProps {
  page: number;              // 1-based
  pageSize: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  /** Accessible label describing what list is paginated, e.g. "security findings". */
  itemLabel?: string;
}

function pageWindow(page: number, totalPages: number): number[] {
  // Show up to 5 page numbers centered on the current page.
  const start = Math.max(1, Math.min(page - 2, totalPages - 4));
  const end = Math.min(totalPages, start + 4);
  const pages: number[] = [];
  for (let p = Math.max(1, start); p <= end; p++) pages.push(p);
  return pages;
}

export const Pagination: React.FC<PaginationProps> = ({
  page,
  pageSize,
  totalItems,
  onPageChange,
  itemLabel = "items",
}) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  if (totalItems === 0 || totalPages <= 1) return null; // nothing to paginate

  const safePage = Math.min(Math.max(1, page), totalPages);
  const from = (safePage - 1) * pageSize + 1;
  const to = Math.min(safePage * pageSize, totalItems);
  const pages = pageWindow(safePage, totalPages);

  const btnBase =
    "inline-flex items-center justify-center h-8 min-w-8 px-2 rounded-xl text-xs font-bold border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent-blue disabled:opacity-40 disabled:cursor-not-allowed";

  return (
    <nav
      className="flex flex-wrap items-center justify-between gap-3 mt-4 pt-3 border-t border-zinc-200 dark:border-zinc-800"
      aria-label={`Pagination for ${itemLabel}`}
    >
      <p className="text-xs font-semibold text-zinc-500 dark:text-zinc-400" aria-live="polite">
        Showing {from}–{to} of {totalItems} {itemLabel}
      </p>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className={`${btnBase} border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800`}
          disabled={safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
          aria-label={`Previous page (${safePage - 1} of ${totalPages})`}
        >
          <ChevronLeft className="w-4 h-4" aria-hidden="true" />
          <span className="ml-1 hidden sm:inline">Previous</span>
        </button>
        {pages.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPageChange(p)}
            aria-label={`Page ${p} of ${totalPages}`}
            aria-current={p === safePage ? "page" : undefined}
            className={`${btnBase} ${
              p === safePage
                ? "bg-accent-blue text-white border-accent-blue"
                : "border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            {p}
          </button>
        ))}
        <button
          type="button"
          className={`${btnBase} border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800`}
          disabled={safePage >= totalPages}
          onClick={() => onPageChange(safePage + 1)}
          aria-label={`Next page (${safePage + 1} of ${totalPages})`}
        >
          <span className="mr-1 hidden sm:inline">Next</span>
          <ChevronRight className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>
    </nav>
  );
};

/** Hook: clamp page when the underlying list shrinks (e.g. after filtering). */
export function usePagination<T>(items: T[], pageSize: number) {
  const [page, setPage] = React.useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageItems = items.slice((safePage - 1) * pageSize, safePage * pageSize);
  React.useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  return { page: safePage, setPage, pageItems, totalItems: items.length };
}
