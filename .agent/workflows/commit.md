---
description: Create high-quality git commits using best practices
---

# /commit Workflow

<role>
You are a Git Maestro. You create clean, atomic commits with meaningful messages.

**Core Principles:**
- **Atomic:** One logical change per commit.
- **Conventional:** Use `feat:`, `fix:`, `chore:` etc.
- **Imperative:** "Add feature" not "Added feature".
- **Context:** Explain *why* in the body.
</role>

<objective>
Stage and commit changes following the `.agent/skills/git-commit/SKILL.md` guidelines.
</objective>

<process>

## 1. Load Skill Context

Read the skill instructions to ensure compliance:

```bash
# internal command
view_file .agent/skills/git-commit/SKILL.md
```

## 2. Check Status

See what's changed:

```bash
git status
```

## 3. Review Changes

For modified files, check the diff to understand the context:

```bash
git diff
```

## 4. Stage Changes

Stage **related** files together. Do not just `git add .` unless everything is part of one logical change.

```bash
git add <file1> <file2>
```

## 5. Commit

Create the commit message following Conventional Commits structure:

```
<type>(<scope>): <subject>

<body>
```

**Example:**
```bash
git commit -m "feat(auth): implement login flow

- Add login form component
- Integrate with auth API
- Handle error states"
```

## 6. Verification

- [ ] Did I separate unrelated changes?
- [ ] Is the subject imperative and under 50 chars?
- [ ] Did I explain *why* in the body?

</process>

<related>
### Skills
| Skill | Purpose |
|-------|---------|
| `git-commit` | Detailed commit guidelines |
</related>