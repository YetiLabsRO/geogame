#!/usr/bin/env node
// Renders the PNG sources that @capacitor/assets needs (Custom Mode:
// https://github.com/ionic-team/capacitor-assets#custom-mode) from the castle mark defined
// in icon.svg / splash.svg. Run with:
//
//   node resources/render.mjs && npx capacitor-assets generate --android --ios \
//     --iconBackgroundColor '#974400' --iconBackgroundColorDark '#121416' \
//     --splashBackgroundColor '#fcf9f2' --splashBackgroundColorDark '#121416'
//
// `sharp` is not a direct dependency here; it ships as a transitive dependency of
// @capacitor/assets, so we resolve it from there instead of adding a new devDependency.
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const sharpEntry = require.resolve('sharp');
const { default: sharp } = await import(sharpEntry);

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// The castle mark: a crenellated keep (three merlons) with an arched doorway, as a single
// evenodd path so the doorway is a true hole. Local coordinate space is a 120x130 box with
// its origin at the top-left of the ink (see icon.svg for the derivation). Keep this in sync
// with icon.svg / splash.svg if the shape ever changes.
const CASTLE_PATH_D =
  'M0,130 L0,30 L9,30 L9,0 L37,0 L37,30 L46,30 L46,0 L74,0 L74,30 L83,30 L83,0 L111,0 L111,30 L120,30 L120,130 Z ' +
  'M42,130 L42,70 A18,18 0 0 1 78,70 L78,130 Z';
const CASTLE_INK_WIDTH = 120;
const CASTLE_INK_HEIGHT = 130;

/**
 * Builds a square SVG document with an optional flat background and the castle mark
 * centred at the given ink height (`markHeight`, in px). Pass `bgColor: null` for a fully
 * transparent canvas (used for icon-foreground.png).
 */
function buildSvg({ canvasSize, bgColor, cornerRadius = 0, markColor, markHeight }) {
  const scale = markHeight / CASTLE_INK_HEIGHT;
  const inkWidth = CASTLE_INK_WIDTH * scale;
  const tx = (canvasSize - inkWidth) / 2;
  const ty = (canvasSize - markHeight) / 2;

  const background = bgColor
    ? `<rect width="${canvasSize}" height="${canvasSize}" rx="${cornerRadius}" ry="${cornerRadius}" fill="${bgColor}" />`
    : '';

  const mark = markColor
    ? `<g transform="translate(${tx},${ty}) scale(${scale})">
         <path fill="${markColor}" fill-rule="evenodd" d="${CASTLE_PATH_D}" />
       </g>`
    : '';

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${canvasSize}" height="${canvasSize}" viewBox="0 0 ${canvasSize} ${canvasSize}">${background}${mark}</svg>`;
}

const renders = [
  {
    // Legacy / combined icon: sienna background + white castle, same as icon.svg.
    file: 'icon-only.png',
    svg: buildSvg({ canvasSize: 1024, bgColor: '#974400', cornerRadius: 180, markColor: '#ffffff', markHeight: 560 }),
  },
  {
    // Android adaptive icon foreground layer: transparent canvas, white castle only. Sized
    // to stay within the ~66% adaptive-icon safe zone so no launcher mask clips it.
    file: 'icon-foreground.png',
    svg: buildSvg({ canvasSize: 1024, bgColor: null, markColor: '#ffffff', markHeight: 560 }),
  },
  {
    // Android adaptive icon background layer: flat sienna, no rounding (the OS applies its
    // own mask shape, so this must fill the full canvas edge-to-edge).
    file: 'icon-background.png',
    svg: buildSvg({ canvasSize: 1024, bgColor: '#974400', cornerRadius: 0, markColor: null, markHeight: 560 }),
  },
  {
    // Light splash screen: parchment background, sienna mark, ~400px tall as specified.
    file: 'splash.png',
    svg: buildSvg({ canvasSize: 2732, bgColor: '#fcf9f2', markColor: '#974400', markHeight: 400 }),
  },
  {
    // Dark splash screen: dark background, light-sienna mark so it still reads on dark.
    file: 'splash-dark.png',
    svg: buildSvg({ canvasSize: 2732, bgColor: '#121416', markColor: '#ffb59c', markHeight: 400 }),
  },
];

for (const { file, svg } of renders) {
  const outPath = path.join(__dirname, file);
  await sharp(Buffer.from(svg)).png().toFile(outPath);
  console.log(`wrote ${outPath}`);
}
