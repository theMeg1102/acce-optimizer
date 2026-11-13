export type RoutePreference = { providerId: string; modelId: string };
export type RuntimeRouteIdentity = { providerId: string; modelId: string };

const DIRECTIVE = /\b(?:use|prefer|choose|select|route(?:\s+this)?\s+to|run\s+with|switch\s+to|usa|utiliza|prefiero|prefiere|elige|selecciona|cambia\s+a|quiero\s+usar)\b/giu;
const NEGATED = /(?:\bdo\s+not|\bdon't|\bnever|\bno|\bno\s+uses|\bno\s+utilices|\bno\s+prefieras)\s*$/iu;
const IDENTIFIER_CHAR = /[\p{L}\p{N}_.:/-]/u;

/**
 * Extract an explicitly requested route from the current prompt without retaining
 * or transmitting the prompt. Only exact provider/model identities from OpenClaw's
 * effective config are eligible; ambiguous or negated requests produce no preference.
 */
export function extractExplicitRoutePreference(
  prompt: unknown,
  runtimeRoutes: readonly RuntimeRouteIdentity[],
): RoutePreference | undefined {
  if (typeof prompt !== "string" || prompt.length === 0 || runtimeRoutes.length === 0) return undefined;
  const text = prompt.slice(-100_000);
  const directives = [...text.matchAll(DIRECTIVE)];
  const selected = new Map<string, RoutePreference>();
  let ambiguousDirective = false;

  for (const directive of directives) {
    const start = directive.index ?? 0;
    const before = text.slice(Math.max(0, start - 32), start);
    if (NEGATED.test(before)) continue;
    const tail = text.slice(start + directive[0].length, start + directive[0].length + 180);
    const matches = new Map<string, RoutePreference>();

    for (const route of runtimeRoutes) {
      if (!route.providerId || !route.modelId) continue;
      const reference = `${route.providerId}/${route.modelId}`;
      let offset = tail.indexOf(reference);
      while (offset >= 0) {
        const previous = offset > 0 ? tail[offset - 1] : "";
        const next = tail[offset + reference.length] ?? "";
        const afterNext = tail[offset + reference.length + 1] ?? "";
        const sentencePeriod = next === "." && (!afterNext || afterNext.trim() === "" || ",!?;:)]}>’”".includes(afterNext));
        if ((!previous || !IDENTIFIER_CHAR.test(previous)) &&
            (!next || !IDENTIFIER_CHAR.test(next) || sentencePeriod)) {
          matches.set(reference, { providerId: route.providerId, modelId: route.modelId });
        }
        offset = tail.indexOf(reference, offset + reference.length);
      }
    }

    // A directive mentioning multiple configured routes is not a reliable preference.
    if (matches.size === 1) {
      const [key, value] = matches.entries().next().value as [string, RoutePreference];
      selected.set(key, value);
    } else if (matches.size > 1) {
      ambiguousDirective = true;
    }
  }

  // Conflicting explicit preferences in one prompt are ambiguous; do not guess.
  return !ambiguousDirective && selected.size === 1 ? [...selected.values()][0] : undefined;
}
