## ADDED Requirements

### Requirement: Token contract as CSS custom properties

The system SHALL define the "old-world explorer" design tokens from the Figma design system as CSS custom properties in the shared library, with a Light and a Dark theme.

#### Scenario: Light theme by default

- **WHEN** the player app loads with no theme preference and the OS prefers light
- **THEN** `:root` SHALL expose the Light values (brand `#974400`, canvas `#fcf9f2`, raised `#ffffff`, inset `#ebe8e1`, text primary `#321200`, …) for every semantic colour token, plus spacing (`4/8/12/16/24`), radius (`12/16/24/full`), elevation and typography tokens

#### Scenario: Dark theme

- **WHEN** the OS prefers dark and no explicit light choice is stored, or the player chooses dark in settings
- **THEN** the same token names SHALL resolve to the Dark values (brand `#ffb59c`, canvas `#121416`, raised `#1e2022`, inset `#333537`, text primary `#e2e2e5`, …) and every component SHALL re-theme without component changes

#### Scenario: Runtime team colour

- **WHEN** a component renders team-group identity
- **THEN** it SHALL read the `--team-color` custom property set at runtime from the TeamGroup, never a hard-coded team colour

### Requirement: Typography and icons

The system SHALL self-host the design system's typefaces and icon set.

#### Scenario: Fonts

- **WHEN** the player app renders
- **THEN** headings SHALL use Playfair Display and UI text Plus Jakarta Sans, loaded from bundled font files (no CDN) with system fallbacks, using the Figma text-style sizes, weights, line heights and letter spacing

#### Scenario: Icons

- **WHEN** a screen needs an icon from the design system set (chevron-left, arrow-right, compass, clock, star, camera, sparkle, lightbulb, bell, target, map, users, book, id-card, castle, key)
- **THEN** it SHALL use the shared `ui-icon` component rendering an inline SVG that inherits `currentColor`

### Requirement: Shared UI components

The system SHALL provide the design system's components as standalone Angular components in the shared library, styled only through the token contract.

#### Scenario: Component library

- **WHEN** an app imports from `shared`
- **THEN** it SHALL find `ui-button` (primary/secondary/tinted, sizes, icon slot, loading, block), `ui-chip` (brand/solid/slate/neutral, team colour), `ui-field` with the `uiInput` directive (label, help, error), `ui-card`, `ui-stat-tile`, `ui-progress-meter`, `ui-avatar`, `ui-top-app-bar`, `ui-bottom-nav`, `ui-icon`, `ui-toast` and `ui-empty-state`, each `OnPush` with signal inputs/outputs

#### Scenario: Accessibility

- **WHEN** a component is interactive
- **THEN** it SHALL have a minimum 44px tap target, a visible focus ring, and WCAG AA contrast in both themes

### Requirement: Bootstrap for layout only

The system SHALL restrict Bootstrap in the player app to its grid and utility classes.

#### Scenario: No Bootstrap component styles

- **WHEN** the player app is built
- **THEN** its styles SHALL include only Bootstrap's grid/utilities layers and no Bootstrap component classes (`btn`, `card`, `navbar`, `form-control`, `progress`, `alert`, `modal`, …) SHALL remain in player templates, and the Bootstrap JS bundle SHALL NOT be loaded
