# DESIGN_SYSTEM.md

Default UI system: **shadcn/ui**.

## Rule
For any new UI work in this repo, use shadcn/ui primitives first.

Prompting line to include in UI tasks:
"Use shadcn/ui components as the default design system and compose from those primitives unless explicitly told otherwise."

## Exception path
If this repo/page is static HTML or cannot use shadcn/ui directly, keep the same tokenized design-system structure:
- central CSS variables for color/spacing/type/radius
- reusable UI primitives (button/card/input/badge/layout)
- consistent component API and naming

## Local reference
- `/Users/ryanprendergast/Documents/design-systems/shadcn-ui`
