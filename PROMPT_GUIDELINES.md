# PROMPT_GUIDELINES.md

## UI/Frontend prompting standard
Always include this line in UI generation prompts:

"Use shadcn/ui components as the default design system and compose from those primitives unless explicitly told otherwise. Follow shadcn layout/tokens/radius/spacing conventions."

## Design baseline
- Prefer shadcn primitives (Button, Card, Input, Badge, Tabs, Dialog, Table, Skeleton).
- Use tokenized styling (background/foreground/muted/border/primary).
- Keep spacing and typography consistent with shadcn defaults.
