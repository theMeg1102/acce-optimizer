export type TaskProfile = {
  summary: string;
  urgency: "normal" | "urgent";
  categories: string[];
  taskClass: "coding" | "research" | "analysis" | "general";
};

/** Extract only coarse task categories locally; never return raw prompt text. */
export function deriveTaskProfile(prompt: unknown): TaskProfile {
  const text = typeof prompt === "string" ? prompt.slice(0, 20000).toLowerCase() : "";
  const categories: string[] = [];
  if (/\b(code|coding|program|python|typescript|javascript|sql|debug|compile|repository|script)\b/u.test(text)) categories.push("coding", "programming");
  if (/\b(analy[sz]e|analysis|reason|architecture|trade-?off|evaluate|compare|design)\b/u.test(text)) categories.push("analysis", "reasoning");
  if (/\b(research|sources|citations|latest|current|web search|investigate)\b/u.test(text)) categories.push("research");
  const unique = [...new Set(categories)];
  const taskClass: TaskProfile["taskClass"] = unique.includes("coding") ? "coding" : unique.includes("research") ? "research" : unique.includes("analysis") ? "analysis" : "general";
  const urgency = /\b(urgent|asap|immediately|emergency)\b/u.test(text) ? "urgent" : "normal";
  const summaryCategories = urgency === "urgent" ? [...unique, "urgent"] : unique;
  return {
    summary: `OpenClaw text-generation request; task categories: ${summaryCategories.join(", ") || "general"}`,
    urgency,
    categories: unique.length ? unique : ["general"],
    taskClass,
  };
}
