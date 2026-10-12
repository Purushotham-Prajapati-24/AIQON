/** Who is using the dashboard. Picking a role decides where the page opens and how explanations are worded. */
export type RoleId = "planner" | "support" | "analyst" | "first";

export interface Role {
  id: RoleId;
  name: string;
  /** The job this person comes to do, in their words. */
  task: string;
  /** Section the page opens on. */
  opens: "top" | "fleet" | "shipment" | "proof";
  /** Default wording for the "why" sentence. */
  audience: "ops" | "customer";
}

export const ROLES: Role[] = [
  { id: "planner", name: "Ops planner", task: "Find the shipments that will be late and act on the worst first.", opens: "fleet", audience: "ops" },
  { id: "support", name: "Customer support", task: "Answer “where is my order?” with a date and one clear reason.", opens: "shipment", audience: "customer" },
  { id: "analyst", name: "Network analyst", task: "See where delays grow, and check the model can be trusted.", opens: "proof", audience: "ops" },
  { id: "first", name: "First look", task: "Watch one shipment’s delay unfold in under a minute.", opens: "top", audience: "customer" },
];

export const roleById = (id: string | null) => ROLES.find((r) => r.id === id) ?? null;
