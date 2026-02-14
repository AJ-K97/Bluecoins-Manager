---
description: Create high-quality, atomic git commits following best practices
---

# Git Commit Mastery

> **Core Philosophy**: A commit history acts as documentation. Each commit should tell a story about *why* a change was made, not just *what* changed.

## Principles

1.  **Atomic Commits**: One logical change per commit. Don't mix refactoring with features.
2.  **Conventional Commits**: Use structured prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `style:`, `perf:`).
3.  **Imperative Mood**: "Add feature" (not "Added feature" or "Adds feature"). Matches `git merge` language.
4.  **Meaningful Context**: Explain the *why* in the body if the *what* isn't obvious.

## Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

-   **Header**: `type(scope): subject` (Max 50 chars recommended, 72 hard limit).
-   **Body**: Detailed explanation. Wrap at 72 chars. Separate from header by a blank line.
-   **Footer**: Metadata like `Closes #123`, `Breaking Change: ...`.

### Examples

**Good:**
```
feat(auth): implement JWT token validation

- Add `validate_token` middleware
- Update user schema for tokens
- Add unit tests for expiration logic

Closes #42
```

**Bad:**
```
fixed login and some css
```

## Workflow

1.  **Check Status**: `git status` to see what's changed.
2.  **diff**: `git diff` to review changes.
3.  **Stage**: `git add <file>` (Avoid `git add .` unless you verify all files are related).
4.  **Commit**: `git commit -m "..."`.

## Verification

Before committing, ask:
-   [ ] Does this commit distinct changes?
-   [ ] Is the message in imperative mood?
-   [ ] Is the type correct?
-   [ ] Are unrelated changes excluded?
