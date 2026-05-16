import {
  Link2,
  FileText,
  Mic,
  ListChecks,
  Lightbulb,
  CheckCircle2,
  Circle,
} from "lucide-react";
import type { ThoughtKind } from "../../lib/types";

interface IconTypeProps {
  kind: ThoughtKind;
  size?: number;
  strokeWidth?: number;
  /** Если true — рендерит иконку внутри цветного круглого "аватара" (для chats variant). */
  avatar?: boolean;
}

const KIND_LABEL: Record<ThoughtKind, string> = {
  link: "ссылка",
  article: "статья",
  voice: "голосовая",
  task: "список",
  idea: "идея",
  action: "действие",
  other: "заметка",
};

const KIND_AVATAR_CLASS: Record<ThoughtKind, string> = {
  link: "icon-avatar--sky",
  article: "icon-avatar--dust",
  voice: "icon-avatar--amber",
  task: "icon-avatar--sage",
  idea: "icon-avatar--rose",
  action: "icon-avatar--sage",
  other: "icon-avatar--dust",
};

function renderIcon(kind: ThoughtKind, size: number, strokeWidth: number) {
  const props = { size, strokeWidth, "aria-hidden": true } as const;
  switch (kind) {
    case "link":    return <Link2 {...props} />;
    case "article": return <FileText {...props} />;
    case "voice":   return <Mic {...props} />;
    case "task":    return <ListChecks {...props} />;
    case "idea":    return <Lightbulb {...props} />;
    case "action":  return <CheckCircle2 {...props} />;
    case "other":   return <Circle {...props} />;
  }
}

/**
 * IconType — маппинг ThoughtKind → Lucide иконка + (опционально) цветной круг-«аватар».
 * - inline (default): иконка как есть, размер 14-16px, цвет --fg-3
 * - avatar=true: иконка в круге 48px с цветным background по типу (для chats variant)
 */
export function IconType({ kind, size = 14, strokeWidth = 1.75, avatar = false }: IconTypeProps) {
  if (avatar) {
    return (
      <span className={`icon-avatar ${KIND_AVATAR_CLASS[kind]}`} aria-label={KIND_LABEL[kind]}>
        {renderIcon(kind, 22, 1.6)}
      </span>
    );
  }
  return renderIcon(kind, size, strokeWidth);
}

/** Для preview-строки в chats: <b>статья ·</b> текст */
export function kindLabel(kind: ThoughtKind): string {
  return KIND_LABEL[kind];
}
