# AiMate typography

AiMate uses the native San Francisco system font on macOS and bundled Inter on
Windows and Linux. Buttons, menus, the editor and chat text share the same clean
sans-serif style. Code and logs retain their monospace font; emoji retain their
platform font.

The variable Inter font is served from AiMate itself, so it works offline and
does not contact a font service. Its SIL Open Font License is included beside
the font. `font-display: swap` keeps text readable while it loads; system fonts
remain available if the asset cannot load.

This is an optional stylesheet. Remove the `typography.css` link or set
`data-typography="system"` on the HTML element to restore the original font.
Themes, text sizes and user data are independent of this module.

Source: https://github.com/rsms/inter — `docs/font-files/InterVariable.woff2`.
