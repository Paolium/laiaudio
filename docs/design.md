# Design system

Laiaudio uses the Paolium dark palette with the Sapphire accent. Colors are defined once, as libadwaita CSS
variables and component classes, in the `CSS` string of `app.py`; the color scheme is forced to dark.

## Colors

| Token | Value | Use |
| --- | --- | --- |
| Depth | `#000000` | The frame: sidebar, header bar and footer. |
| Base | `#141414` | Window and content background, and the page bars below the header. |
| Surface | `#2C2C2E` | Cards, dialogs content rows, popovers. |
| Border | `#3A3A3C` | Dividers and card borders. |
| Text | `#D6DAE0` | Primary text. |
| Sapphire | `#0D71FD` | Accent: primary buttons, selected states, ES and floating captions toggles, translator dot, "Meeting" speaker (`#5C9DFE`). |
| Ruby | `#FA4F67` | Recording, microphone toggle, destructive actions. |
| Paolium | `#D69D00` | The brand dot in the footer. |
| Carbon | `#95D700` | "Me" speaker. |

## Typography

- System sans for the UI; transcript text at 1.15em for comfortable reading.
- Monospace for the floating captions (fixed line width) and the Markdown source view.
- Brand text ("Paolium") in weight 600 with tight letter spacing, as on paolium.web.app.

## Components and states

- **StateToggle**: no background in any state. On: colored icon or text; hover lightens it and scales icons 12 %.
  Off: muted color with a short diagonal slash; hover restores full contrast.
- **Pill bar**: rounded group on Base with a Border outline; the checked button uses a 22 % Sapphire fill. Action
  icons turn Sapphire on hover (Delete turns Ruby); `StateToggle`s inside a pill bar keep their own colors.
- **Live dot**: ruby on hover; ruby and softly pulsing (1.6 s) while recording.
- **Translator dot**: muted gray; lighter on hover; sapphire while the translator is open.
- **Floating captions**: Base at 88 % opacity, Border outline, 10 px radius, two fixed monospace lines.
