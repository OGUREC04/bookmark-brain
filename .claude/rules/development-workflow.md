# Development Workflow

> Extends [git-workflow.md](~/.claude/rules/common/git-workflow.md) with the full dev pipeline.

## Feature Implementation Workflow

0. **Research & Reuse** _(mandatory before any new implementation)_
   - **GitHub code search first:** `gh search repos` and `gh search code`
   - **Library docs second:** Context7 or vendor docs
   - **Check package registries:** npm, PyPI before writing utility code
   - Prefer adopting proven approach over writing net-new code

1. **Plan First**
   - Use **planner** agent for implementation plan
   - Identify dependencies and risks
   - Break down into phases

2. **TDD Approach**
   - Use **tdd-guide** agent
   - RED → GREEN → IMPROVE
   - Verify 80%+ coverage

3. **Code Review**
   - Use **code-reviewer** agent immediately after writing code
   - Address CRITICAL and HIGH issues

4. **Commit & Push**
   - Conventional commits format
   - See git-workflow.md for details

5. **Pre-Review Checks**
   - All CI/CD passing, conflicts resolved, branch up to date
