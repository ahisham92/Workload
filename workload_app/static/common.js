/* Selecao+ — the helpers every page shares.
 *
 * Loaded first on index.html, member.html and login.html, before the page's
 * own scripts, which all use these.
 */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Replace a node's children, treating a null child as nothing at all.
 *
 *  Every render builds its children with ternaries, and the DOM's own
 *  replaceChildren turns a null into the text "null" on the page.
 */
function setChildren(node, ...children) {
  node.replaceChildren(
    ...children.filter((child) => child !== null && child !== undefined));
}

/** A plain element, for the scripts that run without the page's own `el`
 *  (pocket.js runs on the sign-in page too). */
function make(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/* Where this page is served from. At an address of its own that is the root
   and BASE is empty; as one tab of a larger site it is "/workload", and every
   request has to be made under it rather than at the site's root. */
const BASE = new URL('.', window.location.href).pathname.replace(/\/$/, '');

/** A failed request's messages, as a toast (the page's own `toast`). */
/** An error's words, each said once: a plain error repeats its message as its
    only error, and showing both printed it twice. */
function errorText(error) {
  return [...new Set([error.message, ...(error.errors || [])])].join(' ');
}

function toastError(error) {
  toast((error.errors || [error.message]).join(' '), 'bad');
}

/* -- the phone ----------------------------------------------------------- */

const isApple = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
/** Opened from the home screen, without the browser's bars around it. */
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches
  || window.navigator.standalone === true;

/* -- dates --------------------------------------------------------------- */

/** "2026-10-08" (or "2026-10-08T16:43:15+00:00") as "08/10/2026"; '—' when blank.
 *  Anything that is not an ISO date is shown as it came. */
function dayFirst(v) {
  if (v === null || v === undefined || v === '') return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : String(v);
}

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Every ISO date inside a sentence the server wrote, made day-first:
 *  "2026-10-08" as "08/10/2026", and "since 2026-06" as "since Jun 2026". A
 *  bare "2026-06" is only read as a month after a word like "since", so a job
 *  number that happens to look like one is left alone. */
function dayFirstText(text) {
  if (text === null || text === undefined) return text;
  return String(text)
    .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, '$3/$2/$1')
    .replace(/\b(since|in|from|to|until|till|of|by|before|after|for) (\d{4})-(0[1-9]|1[0-2])\b(?!-)/gi,
      (_, word, y, mo) => `${word} ${MONTH_NAMES[Number(mo) - 1]} ${y}`);
}

/** An ISO date written the en-GB way, whatever the phone's locale: "Thu 8 Oct",
 *  or as `opts` asks; '—' when there is none. */
function dateText(iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) {
  if (!iso) return '—';
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', opts);
}

/** The same for a date or a timestamp (only its day is shown); '' when there is none. */
function dayLabel(iso, opts) {
  return iso ? dateText(iso.slice(0, 10), opts) : '';
}
