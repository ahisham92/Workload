/* Selecao+ — what every number means, a tap away.
 *
 * Each percentage and key figure gets a small "i" beside its name. Tapping it
 * says, in plain words, what the number is, how it is worked out and what
 * good looks like. The buttons are added on their own wherever a card, table
 * heading or key carries one of the names below, on every tab, so a new
 * screen gets them by using the same names.
 *
 * Loaded after common.js on index.html and member.html.
 */
'use strict';

/** The meanings: what it is, how it is worked out, what good looks like. */
const MEANINGS = {
  utilisation: {
    title: 'Busy on real work',
    what: 'How much of the time someone was there to work went on projects and proposals.',
    how: 'Hours on projects and proposals divided by the hours they were there to work: a full timesheet for the working days so far, less their leave and holidays. Hours on general and department codes are the gap. It counts up to today, or up to the last day the timesheets reach if they stop earlier, never the whole year. Days with nothing on the timesheet are shown apart, as days not filled in yet.',
    good: '85% to 105% is about right. Over 105% is overtime: too much on their plate. 70% to 85% is light: they have room for more. Under 70%: they are spending their days on general and department codes, so find them work.',
  },
  bands: {
    title: 'The colours',
    what: 'How busy each person was on real work, as a colour.',
    how: 'Green (on plan) is 85% to 105% of the hours they were there to work. Amber (light) is 70% to 85%. Red is under 70% or over 105%.',
    good: 'Green for everyone. Red over 105%: take work off them. Red under 70%: give them work.',
  },
  not_filled: {
    title: 'Days not filled in yet',
    what: 'Working days with nothing on someone’s timesheet so far.',
    how: 'The hours a full timesheet holds for the working days so far, less every hour they booked (leave included), in whole days.',
    good: 'None. If there are some, ask them to fill those days in: until they do, those empty days pull their busy-on-real-work % down.',
  },
  cpi: {
    title: 'Efficiency (CPI)',
    what: 'How much value the work delivered for each man-month spent on it.',
    how: 'Earned MM divided by actual MM booked to projects. Earned is each project’s budget times how far it has got.',
    good: '1.00 or more: the work earns what it costs. 0.80 to 1.00: watch it. Under 0.80: the work is costing more than it earns, so look at that project.',
  },
  type_cpi: {
    title: 'Efficiency, type-weighted',
    what: 'Efficiency (CPI), with harder kinds of work counting for more.',
    how: 'Earned MM scaled by the project type’s weight (Reference > Project types), divided by actual MM.',
    good: '1.00 or more is good. It is what the Scorecard ranks people on, so compare people within the same grade.',
  },
  plan_adherence: {
    title: 'Plan adherence',
    what: 'Whether the effort spent so far matches what was planned so far.',
    how: 'Actual MM divided by planned MM to date. Planned is each project’s budget spread evenly from its start to its end date.',
    good: 'Close to 100% (85% to 115%). Far under means work is slipping behind the plan. Far over means it is taking more effort than planned.',
  },
  plan_earned: {
    title: 'Planned work done',
    what: 'How much of the value planned so far has actually been delivered.',
    how: 'Earned MM divided by planned MM to date.',
    good: '90% or more: the work is keeping up with the plan. Under that, it is falling behind.',
  },
  plan_kept: {
    title: 'Planned hours kept',
    what: 'How much of the week’s plan the timesheets show was really done.',
    how: 'For each job in the copy of the week’s plan, the planned hours or the hours booked to it, whichever is less, over all the planned job hours.',
    good: '80% or more. Lower means work came in on top or the plan was too full; the reasons below say which.',
  },
  tasks_done: {
    title: 'Planned tasks done',
    what: 'How many of the tasks planned for the week were finished.',
    how: 'Tasks in the week’s plan marked done, over all of them.',
    good: '80% or more.',
  },
  planned_mm: {
    title: 'Planned MM',
    what: 'The effort the projects said they would take in this period, in man-months.',
    how: 'Each project’s budget spread evenly between its start and end dates, added up for the months in the period.',
    good: 'Not good or bad on its own: compare it with Actual MM (plan adherence).',
  },
  actual_mm: {
    title: 'Actual MM',
    what: 'The effort really booked to projects in this period, in man-months.',
    how: 'Timesheet hours on project jobs divided by the unit’s hours per man-month (Settings). Proposals, general codes and leave are not project effort, so they are not in it.',
    good: 'Close to Planned MM, and below Earned MM.',
  },
  earned_mm: {
    title: 'Earned MM',
    what: 'The value delivered, in man-months of budget.',
    how: 'Each project’s budget times how far it has got. A 20 MM project that is 40% done has earned 8 MM, however long it took.',
    good: 'Higher than Actual MM: the work is worth more than it cost.',
  },
  profit: {
    title: 'Profit / (loss)',
    what: 'Value delivered less effort spent.',
    how: 'Earned MM minus actual MM.',
    good: 'Above zero. A loss in brackets means the work cost more than it earned so far.',
  },
  in_hand: {
    title: 'In-hand budget',
    what: 'The budget of the work the team has: projects active or not started yet.',
    how: 'The budget MM of every project in scope, added up.',
    good: 'Enough to keep everyone busy for the months ahead. Compare it with the team’s capacity.',
  },
  budget_mm: {
    title: 'Budget MM',
    what: 'What the job is allowed to cost, in man-months.',
    how: 'From the project’s budget (Projects tab, or the BISpark import on Budgets).',
    good: 'Actual should stay under it until the job is done.',
  },
  remaining: {
    title: 'Remaining MM',
    what: 'The work still to do, in man-months of budget.',
    how: 'Cost at completion less what has been booked so far, for work in scope and live.',
    good: 'Compare it with the time the team has left on the job.',
  },
  progress: {
    title: '% complete',
    what: 'How far the project has got.',
    how: 'From each deliverable’s step, weighted by how much of the project it is (Rules of credit on Reference).',
    good: 'In step with the effort spent: 50% done on 50% of the budget is on track.',
  },
  cost_at_completion: {
    title: 'Cost at completion',
    what: 'What the job will have cost by the time it is finished, if it carries on as it is going.',
    how: 'Actual MM divided by % complete, unless a figure is typed in on the project.',
    good: 'At or under the budget.',
  },
  capacity: {
    title: 'Capacity',
    what: 'The hours someone could work in a month: a full timesheet.',
    how: 'The unit’s hours per man-month, times their availability for that year (Team tab).',
    good: 'Booked hours close to it. A dashed line on the charts shows it.',
  },
  man_month: {
    title: 'MM (man-month)',
    what: 'One person’s full month of work.',
    how: 'Hours divided by the unit’s hours per man-month (Settings).',
    good: '',
  },
  hero: {
    title: 'Hero',
    what: 'The person with the best weighted score for that month, or for the whole period.',
    how: 'The Scorecard factors (Reference > Scorecard factors), each scored against the best in the team and weighted. Only finished months are scored.',
    good: 'A pat on the back, not a judgement: compare people within the same grade.',
  },
  project_of: {
    title: 'Project of the period',
    what: 'The finished project that earned the most for the effort spent.',
    how: 'Finalised projects with real effort booked in the period, ranked by efficiency (CPI).',
    good: '',
  },
  score: {
    title: 'Score',
    what: 'One number from 0 to 100 for how someone did in the period.',
    how: 'Each Scorecard factor is scored out of 100 (against the best in the team, or against its target), then weighted.',
    good: '80 or more is strong, 60 to 80 is fair, under 60 needs a talk.',
  },
  share_of_time: {
    title: 'Share of team time',
    what: 'How much of the team’s project effort was this person’s.',
    how: 'Their actual MM divided by the whole team’s.',
    good: 'Not good or bad on its own.',
  },
  first_time_right: {
    title: 'First time right',
    what: 'Submissions approved without coming back for changes.',
    how: 'Submissions returned Code A or B the first time, over all submissions.',
    good: 'The higher the better; Code C returns are rework.',
  },
  free_hours: {
    title: 'Free hours',
    what: 'Hours nobody has planned yet.',
    how: 'Each person’s working hours, less leave, meetings, team time and the tasks planned for them.',
    good: 'A little room is healthy. Lots of free hours means give that person the next job.',
  },
  booked_week: {
    title: 'Booked last week',
    what: 'How full the team’s timesheets were last week.',
    how: 'Hours booked last week divided by the hours of a full week, for everyone together.',
    good: '85% to 105%. Over: overtime. Under 75%: hours missing or not enough work.',
  },
  overtime: {
    title: 'Overtime',
    what: 'Hours booked past people’s normal day.',
    how: 'The overtime hours on the timesheets.',
    good: 'Close to nothing. Overtime week after week means too much work for the team.',
  },
  goals_met: {
    title: 'Goals met',
    what: 'How many of the reviewed goals were reached.',
    how: 'Met counts 100, partly met 50, not met 0, averaged over the goals reviewed so far.',
    good: '70% or more is good, 40% to 70% is fair, under 40% needs a look.',
  },
  dev_time: {
    title: 'Development time',
    what: 'Time kept every week for learning.',
    how: 'Juniors 3 h a week, everyone else 2 h, kept free in the plan.',
    good: 'Kept every week, never booked over.',
  },
  hours_kind: {
    title: 'Where the hours went',
    what: 'What the hours on the timesheets were booked to.',
    how: 'Project work: jobs in the register. Proposals: BISpark job types 2 and 3 (proposals). General and department: any other code, such as GENERAL.DEPT, training or admin. Leave and absence: the codes listed as non-project on Reference (leave, public holiday, excuse).',
    good: 'Projects and proposals are the real work in “Busy on real work”. Leave and holidays come off the time there was to work. General and department hours are the gap. Only project work counts as project effort (Actual MM).',
  },
  load_heat: {
    title: 'The colours',
    what: 'How much of their hours each person booked, or has lined up ahead.',
    how: 'Hours booked (leave included), or work planned for the weeks ahead, over a full timesheet for the same days. This month counts its working days so far.',
    good: 'Room: under 85%. About right: 85% to 105%. Heavy: up to 120%. Over: more than 120%.',
  },
};

/** Which names carry which meaning: an exact name, or a pattern. */
const MEANING_NAMES = [
  [/^(utilisation( vs capacity)?|busy|busy on real work|real work)$/i, 'utilisation'],
  [/^days not filled in yet$/i, 'not_filled'],
  [/^(plan adherence|on plan)$/i, 'plan_adherence'],
  [/^plan earned$/i, 'plan_earned'],
  [/^earning per hour spent$/i, 'cpi'],
  [/^ring: (hours used|busy on real work)$/i, 'utilisation'],
  [/^(on plan|light|over, or far under|over 105% or under 70%)(\s|$)/i, 'bands'],
  [/^(efficiency \(cpi\)|cpi)$/i, 'cpi'],
  [/^(efficiency \(cpi, type-weighted\)|type-weighted cpi)$/i, 'type_cpi'],
  [/^planned( mm)?( to date)?$/i, 'planned_mm'],
  [/^planned hours kept$/i, 'plan_kept'],
  [/^planned tasks done$/i, 'tasks_done'],
  [/^actual( mm)?( booked)?$/i, 'actual_mm'],
  [/^earned( mm)?$/i, 'earned_mm'],
  [/^profit( mm| \/ \(loss\))?$/i, 'profit'],
  [/^in-hand budget$/i, 'in_hand'],
  [/^budget mm$/i, 'budget_mm'],
  [/^remaining( mm)?$/i, 'remaining'],
  [/^% compl\.?$/i, 'progress'],
  [/^cost at compl\.?$/i, 'cost_at_completion'],
  [/^(capacity( mm)?( to date)?|capacity\/month|hours \/ month)$/i, 'capacity'],
  [/^hero of /i, 'hero'],
  [/^project of /i, 'project_of'],
  [/^(score|weighted score)$/i, 'score'],
  [/^share of team time$/i, 'share_of_time'],
  [/^first time right$/i, 'first_time_right'],
  [/^free (hours )?this week$|^free hours, the next two weeks$/i, 'free_hours'],
  [/^booked last week$/i, 'booked_week'],
  [/^overtime( last week)?$/i, 'overtime'],
  [/^goals met$/i, 'goals_met'],
  [/^development time$/i, 'dev_time'],
  [/^where the hours went$/i, 'hours_kind'],
  [/^(room|has room|about right|heavy|over|over their hours)$/i, 'load_heat'],
];

/** The places a number's name sits. */
const MEANING_SPOTS = '.label, .stat-label, .measure-label, .dl-label, th, tbody td:first-child, .legend-item, .hm-key span, .chart-title';

/** The meaning a name carries, if any. */
function meaningFor(name) {
  const text = String(name || '').replace(/\s+/g, ' ').trim();
  const hit = MEANING_NAMES.find(([pattern]) => pattern.test(text));
  return hit ? hit[1] : null;
}

/** A small "i" that explains one meaning when tapped. */
function meaningButton(key) {
  const meaning = MEANINGS[key];
  if (!meaning) return null;
  return make('button', {
    class: 'why-btn', type: 'button', 'data-meaning': key,
    'aria-label': `What does ${meaning.title} mean?`, title: `What does ${meaning.title} mean?`,
  }, 'i');
}

/** The text of a spot without the button already in it. */
function ownText(node) {
  return Array.from(node.childNodes)
    .filter((child) => !(child.classList && child.classList.contains('why-btn')))
    .map((child) => child.textContent).join('');
}

/** Put the buttons in under ``root``, once each. */
function explainIn(root) {
  if (!root || !root.querySelectorAll) return;
  const spots = root.matches && root.matches(MEANING_SPOTS) ? [root] : [];
  spots.push(...root.querySelectorAll(MEANING_SPOTS));
  for (const spot of spots) {
    if (spot.querySelector('.why-btn') || spot.closest('.why-pop')) continue;
    const key = meaningFor(ownText(spot));
    // One "i" for a whole key or legend: its first item carries it.
    if (!key || (spot.parentElement
        && spot.parentElement.querySelector(`.why-btn[data-meaning="${key}"]`))) continue;
    spot.append(meaningButton(key));
  }
}

/* -- the panel that opens ------------------------------------------------- */

let meaningPop = null;

function closeMeaning() {
  if (meaningPop) { meaningPop.remove(); meaningPop = null; }
}

function openMeaning(button) {
  const key = button.dataset.meaning;
  const meaning = MEANINGS[key];
  closeMeaning();
  if (!meaning) return;
  const row = (label, text) => (text ? make('div', { class: 'why-row' },
    make('b', {}, label), make('p', {}, text)) : null);
  meaningPop = make('div', { class: 'why-pop', role: 'dialog', 'aria-label': meaning.title },
    make('div', { class: 'why-head' },
      make('h4', {}, meaning.title),
      make('button', { class: 'why-close', type: 'button', 'aria-label': 'Close',
                       onclick: closeMeaning }, '×')),
    row('What it is', meaning.what),
    row('How it is worked out', meaning.how),
    row('What good looks like', meaning.good));
  document.body.append(meaningPop);
  // Beside the button on a desk; across the bottom on a phone (the CSS).
  if (window.innerWidth > 640) {
    const box = button.getBoundingClientRect();
    const pop = meaningPop.getBoundingClientRect();
    const left = clamp(box.left + box.width / 2 - pop.width / 2, 8, window.innerWidth - pop.width - 8);
    const below = box.bottom + 8;
    const top = below + pop.height > window.innerHeight - 8 ? Math.max(8, box.top - pop.height - 8) : below;
    meaningPop.style.left = `${left}px`;
    meaningPop.style.top = `${top}px`;
  }
  meaningPop.querySelector('.why-close').focus();
}

// Capture, so a tap on the "i" in a sortable heading does not sort the table.
document.addEventListener('click', (event) => {
  const button = event.target.closest && event.target.closest('.why-btn');
  if (button) {
    event.preventDefault();
    event.stopPropagation();
    if (meaningPop && meaningPop.dataset.for === button.dataset.meaning) { closeMeaning(); return; }
    openMeaning(button);
    meaningPop.dataset.for = button.dataset.meaning;
    return;
  }
  if (meaningPop && !meaningPop.contains(event.target)) closeMeaning();
}, true);
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMeaning(); });
window.addEventListener('scroll', closeMeaning, { passive: true });

// New screens get their buttons as they are drawn.
let meaningQueue = [];
const meaningWatch = new MutationObserver((changes) => {
  if (!meaningQueue.length) {
    requestAnimationFrame(() => {
      const nodes = meaningQueue; meaningQueue = [];
      for (const node of nodes) if (node.isConnected) explainIn(node);
    });
  }
  for (const change of changes) {
    for (const node of change.addedNodes) if (node.nodeType === 1) meaningQueue.push(node);
  }
});
document.addEventListener('DOMContentLoaded', () => {
  explainIn(document.body);
  meaningWatch.observe(document.body, { childList: true, subtree: true });
});
