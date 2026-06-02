# Addy Design System

## Summary

Addy is a compact utility UI with a dark neo-brutalist identity: asymmetric leaf-shaped controls, thick black borders, hard offset shadows, vivid violet surfaces, and high-contrast copy actions.

## Color

- Background: `#0c0a14`, dark violet-black.
- Primary surface: `#8252e9`, Addy violet.
- Hover surface: `#9b70ff`, lighter violet.
- Border and shadow: `#000000`.
- Primary text: `#ffffff`.
- Secondary text: `#e2daff`.
- Accent: `#ffd23f`, yellow for connected network labels and pressed states.
- Success: `#10b981` or `#16a34a` for copied feedback.
- Button fill: `#ffffff` with dark ink text.

## Typography

Use a familiar sans family per platform. Desktop prefers Segoe UI, SF Pro Text, or Cantarell. Android uses Kivy's native/default sans. Labels are compact, bold where scannability matters, and never decorative.

## Components

- App header: logo, `ADDY`, and a leaf-shaped refresh action.
- Section label: `Active network interfaces`, left aligned above the list.
- Interface card: leaf-shaped violet panel with black border and offset shadow.
- Copy button: compact leaf-shaped white button with black border and shadow, turning green after copy.
- Empty state: plain inline message inside an Addy surface, no modal or splash screen.

## Layout

The primary screen is the usable network list. Cards stack vertically with consistent spacing. Mobile keeps the same visual language but allows wider touch targets and responsive truncation for long adapter names and IPv6 addresses.

## Motion And Feedback

Use immediate state feedback only. Copy buttons change to a success color briefly, then return to their default state. Avoid decorative page-load motion.
