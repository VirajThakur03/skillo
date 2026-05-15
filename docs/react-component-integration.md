# React Component Integration Note

This repository is currently a Flask + Jinja application, not a `Next.js` / `shadcn/ui` frontend app.

## Current Frontend Reality
- There is no React application runtime in the repo.
- There is no `tailwind.config.js`.
- There is no shadcn UI setup.
- `package.json` is only used for Playwright E2E tooling.
- A `tsconfig.json` exists, but it is not powering a React frontend here.

## Why `/components/ui` Matters In shadcn Projects
In a shadcn setup, `/components/ui` becomes the canonical location for reusable design-system primitives. Keeping that folder consistent matters because:
- generated components assume a predictable home
- imports stay stable across the app
- team members know where base UI primitives live
- it separates low-level UI building blocks from feature-specific components

## If You Want To Add The Provided TSX Component Properly
You would first need a real React frontend, ideally a Next.js app. Typical setup:

```bash
npx create-next-app@latest sklio-web --typescript --tailwind --app
cd sklio-web
npx shadcn@latest init
npm install motion lucide-react
```

Then place the shared UI primitive here:

```text
/components/ui/modern-animated-sign-in.tsx
```

And its demo or feature wrapper here:

```text
/components/blocks/demo.tsx
```

If your shadcn init selects another component base path, create `/components/ui` anyway for consistency and move shared primitives there before wider adoption.

## Tailwind / globals requirements for that component
The provided TSX component also expects:
- Tailwind utility classes
- a `cn` helper at `@/lib/utils`
- Next `Image`
- the `motion` package
- the theme tokens and animations supplied in the component instructions

## What Was Done Instead In This Repo
Because this codebase is not a React app yet, the login/register page was redesigned directly in:

```text
app/templates/demo_login.html
```

That keeps all existing Flask auth flows, IDs, API requests, redirects, and verification behavior intact while matching the website’s color system and visual language more closely.
