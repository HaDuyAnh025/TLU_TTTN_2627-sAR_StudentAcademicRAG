import { CitationBadge } from "@/components/student/CitationBadge";
import type { Citation } from "./types";

type Block =
  | { type: "p"; text: string }
  | { type: "ol"; items: string[] };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const item = /^\d+\.\s+(.*)$/.exec(line);
    if (item) {
      const last = blocks[blocks.length - 1];
      if (last?.type === "ol") last.items.push(item[1]);
      else blocks.push({ type: "ol", items: [item[1]] });
    } else {
      blocks.push({ type: "p", text: line });
    }
  }
  return blocks;
}

interface InlineProps {
  text: string;
  citations: ReadonlyArray<Citation>;
  selectedN: number | null;
  onSelect?: (n: number) => void;
}

function Inline({ text, citations, selectedN, onSelect }: InlineProps) {
  return (
    <>
      {text.split(/(\[\d+\])/g).map((part, i) => {
        const m = /^\[(\d+)\]$/.exec(part);
        if (!m) return part;
        const n = Number(m[1]);
        const citation = citations.find((c) => c.n === n);
        // Chỉ chèn ô số khi câu trả lời thực sự có nguồn số đó (khi đang hiện dần: ô tĩnh).
        if (!citation && citations.length > 0) return part;
        return (
          <CitationBadge
            key={i}
            n={n}
            title={citation?.title}
            selected={selectedN === n}
            onSelect={citation ? onSelect : undefined}
          />
        );
      })}
    </>
  );
}

export interface AnswerContentProps {
  text: string;
  citations: ReadonlyArray<Citation>;
  selectedN: number | null;
  onSelectCitation?: (n: number) => void;
}

/** Hiển thị câu trả lời: đoạn văn, danh sách đánh số và số trích dẫn [n] tương tác. */
export function AnswerContent({ text, citations, selectedN, onSelectCitation }: AnswerContentProps) {
  const blocks = parseBlocks(text);
  return (
    <div className="flex flex-col gap-3 text-body-lg text-text-primary">
      {blocks.map((block, i) =>
        block.type === "ol" ? (
          <ol key={i} className="list-decimal space-y-2 pl-6">
            {block.items.map((item, j) => (
              <li key={j}>
                <Inline
                  text={item}
                  citations={citations}
                  selectedN={selectedN}
                  onSelect={onSelectCitation}
                />
              </li>
            ))}
          </ol>
        ) : (
          <p key={i}>
            <Inline
              text={block.text}
              citations={citations}
              selectedN={selectedN}
              onSelect={onSelectCitation}
            />
          </p>
        ),
      )}
    </div>
  );
}
