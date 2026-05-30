# Instrucciones de trabajo

- Antes de ejecutar un comando que pida permisos explicá en una línea qué va a hacer y por qué
- Antes de codear siempre hacé un resumen de los cambios para que el usuario sepa lo que va a cambiar y preguntá si está bien
- Si te doy la orden AFK trabajá de forma autónoma sin pedir confirmación salvo cambios destructivos
- Cada vez que estés a punto de hacer un build de una aplicación o al terminar un cambio en el código de más de 10 líneas, hacé commit automático con mensaje descriptivo y actualizá el CONTEXTO.md
- Leé CONTEXTO.md al empezar la sesión o cuando escriba CONTEXTO como prompt

## Comando: salir

Cuando el usuario escriba "salir", ejecutá estos pasos en orden sin pedir confirmación:

1. **Actualizá CONTEXTO.md**: Reescribí las secciones "Estado del proyecto", "Pendientes" y "Notas" con todo lo trabajado en esta sesión — qué se hizo, qué decisiones se tomaron, qué falta.
2. **Commit**: `git add -A` y `git commit -m "sesión: <resumen de 1 línea de lo hecho hoy>"`
3. **Push**: `git push` (si hay remote configurado; si no, avisá que falta configurarlo con `git remote add origin <url>`)
4. **Resumen de sesión**: Mostrá al usuario un bloque con: qué se hizo, qué quedó pendiente, y cómo arrancar la próxima sesión.
5. **Cerrá con**: `/exit`

---

# Behavioral guidelines (Karpathy)

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
