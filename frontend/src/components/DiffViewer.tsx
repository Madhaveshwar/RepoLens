import React from "react";

interface DiffViewerProps {
  originalCode: string;
  fixedCode: string;
  filename?: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ originalCode, fixedCode, filename }) => {
  const originalLines = originalCode ? originalCode.split("\n") : [];
  const fixedLines = fixedCode ? fixedCode.split("\n") : [];

  const maxLines = Math.max(originalLines.length, fixedLines.length);

  // Simple line-by-line diff mapping
  const renderLines = () => {
    const rows = [];
    for (let i = 0; i < maxLines; i++) {
      const origLine = originalLines[i] !== undefined ? originalLines[i] : "";
      const fixedLine = fixedLines[i] !== undefined ? fixedLines[i] : "";

      const hasOrig = originalLines[i] !== undefined;
      const hasFixed = fixedLines[i] !== undefined;

      const isDifferent = origLine !== fixedLine;

      let leftBg = "bg-transparent";
      let rightBg = "bg-transparent";
      let leftColor = "text-zinc-500";
      let rightColor = "text-zinc-500";

      if (isDifferent) {
        if (hasOrig && hasFixed) {
          // Modification
          leftBg = "bg-red-950/40";
          rightBg = "bg-green-950/40";
          leftColor = "text-red-300";
          rightColor = "text-green-300";
        } else if (hasOrig) {
          // Deletion
          leftBg = "bg-red-950/40";
          leftColor = "text-red-300";
        } else if (hasFixed) {
          // Addition
          rightBg = "bg-green-950/40";
          rightColor = "text-green-300";
        }
      }

      rows.push(
        <div key={i} className="flex border-b border-border/10 hover:bg-zinc-800/10 text-xs font-mono select-text">
          {/* Left Column: Original */}
          <div className={`w-1/2 flex border-r border-border/30 ${leftBg} py-0.5 px-2 min-w-0`}>
            <span className="w-8 text-right pr-2 text-zinc-500 select-none border-r border-border/10 mr-2 shrink-0">
              {hasOrig ? i + 1 : ""}
            </span>
            <span className={`whitespace-pre overflow-x-auto min-w-0 ${leftColor}`}>
              {origLine || " "}
            </span>
          </div>

          {/* Right Column: Fixed */}
          <div className={`w-1/2 flex ${rightBg} py-0.5 px-2 min-w-0`}>
            <span className="w-8 text-right pr-2 text-zinc-500 select-none border-r border-border/10 mr-2 shrink-0">
              {hasFixed ? i + 1 : ""}
            </span>
            <span className={`whitespace-pre overflow-x-auto min-w-0 ${rightColor}`}>
              {fixedLine || " "}
            </span>
          </div>
        </div>
      );
    }
    return rows;
  };

  return (
    <div className="border border-border rounded-xl bg-zinc-950 overflow-hidden shadow-2xl flex flex-col h-full">
      {/* Diff Header */}
      <div className="bg-surface px-4 py-2.5 border-b border-border flex justify-between items-center text-xs text-zinc-600 font-semibold select-none">
        <span className="flex items-center gap-1.5 truncate max-w-xs">
          ðŸ“„ {filename || "Code Diff Comparison"}
        </span>
        <div className="flex gap-4 shrink-0">
          <span className="flex items-center gap-1 text-[10px] text-red-400">
            <span className="w-2.5 h-2.5 bg-red-950 border border-red-500/30 rounded" />
            Original (- deletions)
          </span>
          <span className="flex items-center gap-1 text-[10px] text-green-400">
            <span className="w-2.5 h-2.5 bg-green-950 border border-green-500/30 rounded" />
            Fixed (+ additions)
          </span>
        </div>
      </div>

      {/* Diff Code Grid */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden divide-y divide-border/20 max-h-[400px]">
        {renderLines()}
      </div>
    </div>
  );
};

