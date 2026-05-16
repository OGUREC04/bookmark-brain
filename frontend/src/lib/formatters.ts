// Форматирование дат и сумм для UI карточек.
// Все функции принимают ISO строку (как приходит из backend) и возвращают строку для рендера.

const MONTHS_SHORT = [
  "янв", "фев", "мар", "апр", "мая", "июн",
  "июл", "авг", "сен", "окт", "ноя", "дек",
];

const DAYS_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** «11 мая» / «11 мая 2024» (если не текущий год). */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = d.getDate();
  const month = MONTHS_SHORT[d.getMonth()];
  const year = d.getFullYear();
  const currentYear = new Date().getFullYear();
  if (year === currentYear) return `${day} ${month}`;
  return `${day} ${month} ${year}`;
}

/**
 * Относительное время для chats-варианта (как в Telegram).
 * - сегодня → "14:30"
 * - вчера → "вчера"
 * - 2-6 дней → "пн" / "вт"
 * - >7 дней → "11 мая"
 */
export function formatRelativeDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.floor((today.getTime() - target.getTime()) / 86_400_000);

  if (diffDays === 0) return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  if (diffDays === 1) return "вчера";
  if (diffDays > 1 && diffDays < 7) return DAYS_SHORT[d.getDay()];
  return formatDate(iso);
}

/**
 * Форматирование fire_at напоминания.
 * - <1ч до → "через 30 мин"
 * - сегодня после now → "сегодня 19:00"
 * - завтра → "завтра 9:00"
 * - <7 дней → "в среду 14:00"
 * - >=7 дней → "11 мая 14:00"
 */
export function formatReminderDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const diffMins = Math.round(diffMs / 60_000);

  if (diffMs < 0) return "сейчас";
  if (diffMins < 60) return `через ${diffMins} мин`;

  const timeStr = `${d.getHours()}:${pad2(d.getMinutes())}`;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86_400_000);

  if (diffDays === 0) return `сегодня ${timeStr}`;
  if (diffDays === 1) return `завтра ${timeStr}`;
  if (diffDays > 1 && diffDays < 7) {
    const day = ["в воскресенье", "в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу"][d.getDay()];
    return `${day} ${timeStr}`;
  }
  return `${formatDate(iso)} ${timeStr}`;
}

/** "3/5" для tasklist прогресса. */
export function formatProgress(done: number, total: number): string {
  return `${done}/${total}`;
}
