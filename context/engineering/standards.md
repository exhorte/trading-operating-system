# Engineering Standards

## General

- Keep domain logic out of UI components.
- Keep infrastructure details out of domain models.
- Prefer typed contracts over unstructured objects.
- Prefer small modules with clear responsibility.
- Avoid premature abstraction, but do not mix analysis, decision, execution, and presentation.

## TypeScript

- Use explicit domain types for trading concepts.
- Avoid `any` unless an integration boundary requires it and it is documented.
- Keep mock data typed and isolated.
- Validate external data with schemas when introduced.

## Frontend

- Build the usable dashboard first, not a marketing page.
- Use dense, scannable layouts suitable for trading operations.
- Include empty/loading/error states.
- Make mock/live status obvious.
- Do not show fake execution controls as live controls.

## Documentation

Update context when:

- architecture changes
- domain model changes
- phase completes
- a new decision is made
- an integration contract changes

