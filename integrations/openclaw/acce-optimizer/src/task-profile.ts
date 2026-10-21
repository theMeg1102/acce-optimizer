export type TaskProfile = {
  summary: string;
  urgency: "normal" | "urgent";
  categories: string[];
};

/**
 * Extract a small, non-reversible task-category summary locally.
 * Raw prompt text is never returned, logged, or sent to the Python bridge.
 */
export function deriveTaskProfile(prompt: unknown): TaskProfile {
  const text = typeof prompt === "string" ? prompt.slice(0, 20000).toLowerCase() : "";
  const categories: string[] = [];
  if (/\b(code|coding|program|python|typescript|javascript|sql|debug|compile|repository|script)\b/u.test(text)) {
    categories.push("coding", "programming");
  }
  if (/\b(analy[sz]e|analysis|reason|architecture|trade-?off|evaluate|compare|design)\b/u.test(text)) {
    categories.push("analysis", "reasoning");
  }
  if (/\b(research|sources|citations|latest|current|web search|investigate)\b/u.test(text)) {
    categories.push("research");
  }
  if (/\b(urgent|asap|immediately|emergency)\b/u.test(text)) {
    return {
      summary: `OpenClaw text-generation request; task categories: ${[...new Set([...categories, "urgent"])].join(", ") || "general"}`,
      urgency: "urgent",
      categories: [...new Set([...categories, "urgent"])].length ? [...new Set([...categories, "urgent"])] : ["general"],
    };
  }
  return {
    summary: `OpenClaw text-generation request; task categories: ${[...new Set(categories)].join(", ") || "general"}`,
    urgency: "normal",
    categories: [...new Set(categories)].length ? [...new Set(categories)] : ["general"],
  };
}
