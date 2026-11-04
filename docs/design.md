# Design system

Laiaudio uses the Paolium dark palette with the Sapphire accent. Colors are defined once, as libadwaita CSS
variables and component classes, in the `CSS` string of `app.py`; the color scheme is forced to dark.

## Colors

| Token | Value | Use |
| --- | --- | --- |
| Depth | `#000000` | Sidebar, header bar, sticky bars and footer. |
| Base | `#141414` | Window and content background. |
| Surface | `#2C2C2E` | Cards, dialogs content rows, popovers. |
| Border | `#3A3A3C` | Dividers and card borders. |
| Text | `#D6DAE0` | Primary text. |
| Sapphire | `#0D71FD` | Accent: primary buttons, selected states, ES toggle, "Meeting" speaker (`#5C9DFE`). |
| Ruby | `#FA4F67` | Recording, microphone toggle, destructive actions. |
| Paolium | `#D69D00` | Floating captions toggle and the brand dot in the footer. |
| Carbon | `#95D700` | "Me" speaker. |

## Typography

- System sans for the UI; transcript text at 1.15em for comfortable reading.
- Monospace for the floating captions (fixed line width) and the Markdown source view.
- Brand text ("Paolium") in weight 600 with tight letter spacing, as on paolium.web.app.

## Components and states

- **StateToggle**: no background in any state. On: colored icon or text; hover lightens it and scales icons 12 %.
  Off: muted color with a short diagonal slash; hover restores full contrast.
- **Pill bar**: rounded group on Base with a Border outline; the checked button uses a 22 % Sapphire fill.
- **Meeting rows**: delete button invisible until the row is hovered; ruby icon, no background, on hover.
- **Live dot**: ruby on hover; ruby and softly pulsing (1.6 s) while recording.
- **Floating captions**: Base at 88 % opacity, Border outline, 10 px radius, two fixed monospace lines.
