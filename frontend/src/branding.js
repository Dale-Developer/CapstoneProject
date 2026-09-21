/**
 * Application branding, in one place.
 *
 * The name used to be typed out in six components, the page title, the PWA
 * manifest and the PDF footer. Renaming meant finding all of them, and missing
 * one left the old name visible somewhere nobody looks often -- the browser
 * tab, or the footer of a printed answer sheet.
 *
 * To rename the application, edit VITE_APP_NAME in frontend/.env and restart
 * Vite. Nothing else in the frontend needs touching. The name is read from the
 * environment rather than hardcoded here so that vite.config.js can put the
 * same value into the PWA manifest and index.html, which cannot import from
 * this module.
 *
 * To change the logo, replace src/assets/mainLogo.png and regenerate the PWA
 * icons in public/ (see README_V7_9_9.md). The topbars and the auth screens
 * all read the import below, so one file covers every on-screen appearance.
 *
 * The answer-sheet footer is separate, because it is printed by the backend:
 * set APP_NAME in backend/.env.
 */
import mainLogo from "./assets/mainLogo.png";

export const APP_NAME = import.meta.env.VITE_APP_NAME || "ESSCAN";

// Shown under the installed icon on a phone home screen, where roughly 12
// characters survive before the launcher truncates it.
export const APP_SHORT_NAME = import.meta.env.VITE_APP_SHORT_NAME || APP_NAME;

// Tints the Android status bar and the splash screen of the installed app.
export const APP_THEME_COLOR = import.meta.env.VITE_APP_THEME_COLOR || "#462776";

export const APP_LOGO = mainLogo;
export const APP_LOGO_ALT = `${APP_NAME} logo`;

export default {
  name: APP_NAME,
  shortName: APP_SHORT_NAME,
  themeColor: APP_THEME_COLOR,
  logo: APP_LOGO,
  logoAlt: APP_LOGO_ALT,
};
