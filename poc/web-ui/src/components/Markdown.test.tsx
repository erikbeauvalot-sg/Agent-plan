import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { evidenceLabel, Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders the known subset and never raw HTML", () => {
    const { container } = render(
      <Markdown
        text={
          "## Synthèse\nCause : **CHG0034567** sur `db-pay-02`\n- preuve [lead/calls/0004.json]\n<img src=x onerror=alert(1)>"
        }
        onEvidence={() => {}}
      />,
    );
    expect(container.querySelector("h3")?.textContent).toBe("Synthèse");
    expect(container.querySelector("strong")?.textContent).toBe("CHG0034567");
    expect(container.querySelector("code")?.textContent).toBe("db-pay-02");
    expect(container.querySelector("button.evidence")?.textContent).toBe("principal · appel 4");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("labels evidence by agent and call number", () => {
    expect(evidenceLabel("subagents/T03-metrics-srv-pay-01/calls/0002.json")).toBe("T03 · appel 2");
  });
});
