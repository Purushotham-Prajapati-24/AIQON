/**
 * Wayfinding copy, in one place so the sidebar and the sections never disagree.
 * `question` is what a section answers (shown under its name in the sidebar);
 * `steps` are the things you can do there, in the order you'd do them.
 */
export interface Guide {
  question: string;
  steps: string[];
}

export const GUIDE: Record<string, Guide> = {
  top: {
    question: "One late shipment, step by step",
    steps: ["Press play, or click a milestone to jump to it", "Watch the delay range grow stage by stage", "Scroll on to see the whole fleet"],
  },
  fleet: {
    question: "Which shipments will be late?",
    steps: ["Drag the clock to replay the last 3 weeks", "Click a count, or the chips above the list, to filter by risk", "Click a map dot or a row to open that shipment"],
  },
  shipment: {
    question: "When will it arrive, and why?",
    steps: ["Pick a shipment here, or open one from Fleet or Alerts", "Click a milestone to see what was known then", "Switch the reason to customer or ops wording, then copy it"],
  },
  fix: {
    question: "What would change the outcome?",
    steps: ["Set how busy the port is and switch on a fix", "Compare the new arrival, chance late and cost", "Pick an event under “If this happens” to see who it hits"],
  },
  alerts: {
    question: "What changed this week?",
    steps: ["Filter by severity", "Click an alert to open its shipment"],
  },
  proof: {
    question: "Can the model be trusted?",
    steps: ["Read A to D: error, sharpening, ranges, right cause", "Check “Honest limits” before you rely on a number"],
  },
};
