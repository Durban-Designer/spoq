---
name: skill-maker
description: Create new Claude Code skills following Anthropic best practices. Use when you need to create a new skill for a specific domain or workflow that doesn't exist yet.
---

# Skill Maker - Meta Skill

## When to Use This Skill

Use this skill when:
- You encounter a repetitive workflow that needs standardization
- A new technology stack or pattern needs documentation
- Creating skills for team members to follow
- Documenting domain-specific knowledge
- Building reusable AI assistance templates

## Skill Anatomy

Every skill consists of:
1. **SKILL.md** (required) - Instructions and metadata
2. **scripts/** (optional) - Executable code
3. **references/** (optional) - Documentation loaded on demand
4. **assets/** (optional) - Templates, configs, etc.

## SKILL.md Format

### Required Structure

```markdown
---
name: skill-name-lowercase-with-dashes
description: Clear description of what the skill does and when Claude should use it. Be specific about activation criteria.
---

# Skill Name - Descriptive Title

## When to Use This Skill

Use this skill when:
- Specific condition 1
- Specific condition 2
- File paths or patterns (e.g., "working in documents/latex/")
- Technology stack (e.g., "using NestJS and TypeORM")

## [Main Content Sections]

[Your skill instructions here]

## IMPORTANT Rules

1. Rule 1
2. Rule 2
3. Rule 3

## Integration with SPOQ

- Where this skill's work lives in the repository
- File naming conventions
- Related skills or workflows
```

### YAML Frontmatter Rules

**Required fields:**
- `name` - Must be hyphen-case, lowercase alphanumeric + hyphens only, must match directory name
- `description` - Max 1024 characters, explains what AND when to use

**Optional fields:**
- `license` - License name or file reference
- `allowed-tools` - Tools pre-approved to execute (Claude Code only)
- `metadata` - Custom key-value pairs

**CRITICAL:** The description must be on a single line. Multi-line descriptions (e.g., from auto-formatting) will cause the skill to silently fail discovery.

### Metadata Guidelines

**Name:**
- Lowercase, dash-separated
- Descriptive and unique
- Examples: `java-to-typescript`, `latex-generator`, `skill-maker`

**Description:**
- 1-2 sentences max
- MUST include what it does AND when to use it
- Be specific about activation criteria
- Mention file paths or tech stack when relevant

✅ Good: "Migrate Java Spring Boot applications to TypeScript NestJS with proper patterns. Use when migrating Wyrd services from code/legacy/ to code/apps/."

❌ Bad: "Helps with Java and TypeScript code."

## Content Organization Patterns

### 1. Technical Skills (How-To)

**Structure:**
```markdown
## Core Concepts
[Brief theory]

## Patterns
[Code examples with explanations]

## Common Workflows
[Step-by-step procedures]

## Best Practices
[Do's and don'ts]

## Troubleshooting
[Common issues and solutions]
```

**Example:** `java-to-typescript`, `docker-fullstack`

### 2. Domain Knowledge Skills

**Structure:**
```markdown
## Domain Overview
[Context and background]

## Key Concepts
[Terminology and definitions]

## Implementation Patterns
[How to apply the knowledge]

## Examples
[Concrete use cases]

## Quality Criteria
[How to validate correctness]
```

**Example:** `knowledge-graph-dev`, `python-scientific`

### 3. Workflow/Process Skills

**Structure:**
```markdown
## Workflow Steps
[Ordered process]

## Templates
[Reusable patterns]

## Checklist
[Before/during/after items]

## Integration Points
[How this connects to other work]
```

**Example:** `latex-generator`

## Skill Creation Process

### Step 1: Identify the Need

**Ask these questions:**
- What workflow am I repeating?
- What knowledge keeps getting re-explained?
- What patterns are team members asking about?
- What mistakes keep happening?
- What takes multiple rounds to get right?

### Step 2: Define Activation Criteria

**Be specific about WHEN to use the skill:**
- File paths: "working in code/legacy/"
- Technologies: "using Spring Boot and PostgreSQL"
- Tasks: "creating a new microservice"
- Patterns: "implementing CRUD operations"

### Step 3: Extract Core Patterns

**Identify the 3-5 most important patterns:**
- What's the most common use case?
- What's the most error-prone step?
- What requires the most domain knowledge?
- What has the most reusable code?

### Step 4: Write Examples

**Every pattern needs an example:**
- Show before/after for migrations
- Provide complete code snippets
- Include actual project paths
- Demonstrate common variations

### Step 5: Add Quality Gates

**Define success criteria:**
- Tests that must pass
- Code patterns that must be followed
- Quality metrics to check
- Common mistakes to avoid

## Example: Creating a "React Testing" Skill

### Bad Approach (Too Generic)
```markdown
---
name: react-testing
description: Testing React components
---

# React Testing

Write tests for React components using best practices.
```

### Good Approach (Specific & Useful)
```markdown
---
name: react-testing
description: Test React components using React Testing Library and Jest. Use when creating components in code/apps/*/src/components/ or code/packages/*/components/.
---

# React Testing Skill

## When to Use This Skill

Use this skill when:
- Creating new React components in `code/apps/*/src/components/`
- Adding tests to existing components
- Refactoring components with test coverage
- Using React Testing Library + Jest stack

## Testing Patterns

### Component with Props

```typescript
// Button.tsx
interface ButtonProps {
    onClick: () => void;
    children: React.ReactNode;
    disabled?: boolean;
}

export function Button({ onClick, children, disabled }: ButtonProps) {
    return (
        <button onClick={onClick} disabled={disabled}>
            {children}
        </button>
    );
}

// Button.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from './Button';

describe('Button', () => {
    it('renders children', () => {
        render(<Button onClick={() => {}}>Click me</Button>);
        expect(screen.getByText('Click me')).toBeInTheDocument();
    });

    it('calls onClick when clicked', () => {
        const handleClick = jest.fn();
        render(<Button onClick={handleClick}>Click me</Button>);
        fireEvent.click(screen.getByText('Click me'));
        expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it('is disabled when disabled prop is true', () => {
        render(<Button onClick={() => {}} disabled>Click me</Button>);
        expect(screen.getByText('Click me')).toBeDisabled();
    });
});
```

### Component with State

[More patterns...]

## IMPORTANT Rules

1. EVERY new component requires a test file
2. Test user behavior, not implementation
3. Use `screen.getByRole()` over `getByTestId()`
4. Mock external dependencies
5. Test accessibility (ARIA labels, keyboard navigation)

## Integration with SPOQ

- Tests live alongside components: `ComponentName.test.tsx`
- Run tests with `npm test`
- Coverage minimum: 80%
- CI must pass before merge
```

## Quality Checklist for New Skills

Before finalizing a skill, verify:

✅ **Metadata**
- [ ] Name is descriptive and unique
- [ ] Description includes what AND when
- [ ] Description mentions file paths or tech stack

✅ **Content**
- [ ] 3-5 core patterns documented
- [ ] Each pattern has a complete example
- [ ] Examples use actual project paths
- [ ] Code snippets are copy-paste ready

✅ **Clarity**
- [ ] "When to Use" section is specific
- [ ] No generic advice ("write good code")
- [ ] Technical terms are defined
- [ ] Assumptions are stated

✅ **Actionability**
- [ ] Clear step-by-step processes
- [ ] Checklists for multi-step workflows
- [ ] Error messages and solutions
- [ ] Quality criteria defined

✅ **Integration**
- [ ] Shows where files go in Wyrd structure
- [ ] Mentions related skills
- [ ] Includes Wyrd-specific conventions
- [ ] References actual paths

## Skill Storage

```
.claude/skills/
├── skill-name/
│   ├── SKILL.md              # Required
│   ├── scripts/              # Optional
│   │   └── helper.py
│   ├── references/           # Optional
│   │   └── documentation.md
│   └── assets/               # Optional
│       └── template.txt
```

## Skill Sizes

**Optimal length: 200-400 lines**
- Too short (<100 lines): Might be too generic
- Too long (>600 lines): Split into multiple skills

**If skill gets too large:**
- Extract examples into `references/`
- Move scripts into `scripts/`
- Create specialized sub-skills
- Link related skills in "When to Use"

## Common Antipatterns

❌ **Too Generic**
```markdown
description: "Helps with Python code"
```
✅ **Specific**
```markdown
description: "Create numerical simulations using NumPy, SciPy, and Matplotlib for physics simulations in documents/projects/physics-playground/"
```

❌ **No Context**
```markdown
## Testing
Write tests for your code.
```
✅ **With Context**
```markdown
## Testing in Wyrd
Every new component in code/apps/ requires a .test.tsx file:
- Use React Testing Library
- Minimum 80% coverage
- Test user interactions, not implementation
```

❌ **Missing Examples**
```markdown
Use dependency injection for better testability.
```
✅ **With Example**
```markdown
Use dependency injection for better testability:

```typescript
// Bad: Hard to test
class UserService {
    private db = new Database();
    getUser(id: string) { return this.db.query(...); }
}

// Good: Testable
class UserService {
    constructor(private db: Database) {}
    getUser(id: string) { return this.db.query(...); }
}
```
```

## IMPORTANT Rules for Skill Creation

1. **Be Specific**: Generic advice is useless, specific patterns are gold
2. **Show Examples**: Every pattern needs runnable code
3. **Define Activation**: Clear "when to use" criteria
4. **Quality Gates**: Define what "done" looks like
5. **Wyrd Integration**: Show where files go in the 5-category structure
6. **Iterate**: Skills improve with use, update them
7. **Focus**: One domain per skill, don't create mega-skills

## Using This Skill

When you need a new skill:
1. Identify the workflow/pattern that needs documentation
2. Define specific activation criteria
3. Extract 3-5 core patterns
4. Write complete examples
5. Add quality checklist
6. Create `.claude/skills/new-skill-name/SKILL.md`
7. Use the templates from this skill as a guide

## Integration with SPOQ

- All skills live in `.claude/skills/`
- Skills are automatically loaded by Claude Code
- Can reference other skills in "When to Use" section
- Team shares skills via git in the repository
- Use `skill-maker` to create new skills when patterns emerge
