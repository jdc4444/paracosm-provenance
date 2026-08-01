export type ShotNameInput = {
  isGap?: boolean;
  plannedShotId?: string | null;
  chapter: string;
  sourceClipName?: string | null;
  plannedFileName?: string | null;
  plannedAction?: string | null;
  plannedDescription?: string | null;
};

const TECHNICAL_TOKENS = new Set([
  "A",
  "AS",
  "FINAL",
  "FX",
  "GG",
  "LOTR",
  "IJDKYY",
  "JD",
  "MAIN",
  "NA",
  "ND",
  "NEWFIT",
  "NTH",
  "PATCH",
  "SG",
  "SUB",
  "TH",
]);

const DISPLAY_ACRONYMS = new Set([
  "CU",
  "FX",
  "GG",
  "MTN",
  "NA",
  "POV",
]);

function titleCaseShotName(value: string) {
  return value
    .split(" ")
    .filter(Boolean)
    .map((word) => {
      if (/^\d+[a-z0-9]{1,3}$/i.test(word)) return word.toUpperCase();
      if (DISPLAY_ACRONYMS.has(word.toUpperCase())) return word.toUpperCase();
      if (/^[A-Z0-9]{1,3}$/.test(word)) return word.toUpperCase();
      return `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`;
    })
    .join(" ");
}

function cleanShotName(value?: string | null) {
  if (!value) return "";
  const baseName = value.split(/[\\/]/).at(-1) || value;
  const words = baseName
    .replace(/\.[a-z0-9]{2,5}$/i, "")
    .replace(/coverface/gi, "cover face")
    .replace(/closetexit/gi, "closet exit")
    .replace(/floatspin/gi, "float spin")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/(?:[_ -](?:v|i)\d+)+/gi, " ")
    .replace(/[_ -]\d{2,6}$/g, " ")
    .replace(/([A-Za-z])\d{2,6}$/g, "$1")
    .replace(/[_-]+/g, " ")
    .replace(/\bMTNS?\b/gi, "mountains")
    .replace(/[()]/g, " ")
    .replace(/\b\d{4}\b/g, " ")
    .split(/\s+/)
    .filter(
      (word) =>
        word &&
        !/^[A-Z]$/i.test(word) &&
        !TECHNICAL_TOKENS.has(word.toUpperCase()),
    );
  const deduplicated = words.filter(
    (word, index) =>
      index === 0 || word.toLowerCase() !== words[index - 1].toLowerCase(),
  );
  return titleCaseShotName(
    deduplicated.join(" ").replace(/\s+/g, " ").trim(),
  );
}

function plannedShotCode(
  plannedShotId: string | null | undefined,
  chapter: string,
) {
  if (!plannedShotId) return "";
  const parsed = plannedShotId.match(
    /^(\d+)(?:IJDKYY|NTH|ND|TH|NA|GG)([A-Z]\d?)$/,
  );
  if (parsed) return `${parsed[1]}${parsed[2]}`;
  const withoutChapter = plannedShotId.replace(chapter, "");
  return withoutChapter || plannedShotId;
}

function removeLeadingShotCode(value: string, code: string) {
  if (!code) return value;
  return value
    .replace(
    new RegExp(
      `^${code.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*`,
      "i",
    ),
    "",
    )
    .replace(/^(?:\d+[A-Z0-9]*\s+)+/i, "");
}

function conciseFallback(value?: string | null) {
  if (!value) return "";
  const phrase = value.split(/[,.]/)[0].trim();
  return titleCaseShotName(phrase.split(/\s+/).slice(0, 7).join(" "));
}

export function deriveShotDisplayName({
  isGap,
  plannedShotId,
  chapter,
  sourceClipName,
  plannedFileName,
  plannedAction,
  plannedDescription,
}: ShotNameInput) {
  if (isGap) return "Editorial Gap";

  const code = plannedShotCode(plannedShotId, chapter);
  const candidates = [
    cleanShotName(sourceClipName),
    cleanShotName(plannedFileName),
    conciseFallback(plannedAction),
    conciseFallback(plannedDescription),
  ];
  const descriptive = candidates
    .map((candidate) => removeLeadingShotCode(candidate, code))
    .find(
      (candidate) =>
        candidate &&
        !/^(?:SRC|CLEAN SRC)(?:\s+\d+)?$/i.test(candidate) &&
        !/^\d+[A-Z0-9]*$/i.test(candidate) &&
        candidate.split(/\s+/).some((word) => /[A-Za-z]{4,}/.test(word)),
    );

  if (code && descriptive) return `${code} ${descriptive}`;
  if (descriptive) return descriptive;
  return code || "Untitled Shot";
}
