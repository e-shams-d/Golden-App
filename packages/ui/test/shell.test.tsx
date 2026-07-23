import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ApplicationShell, StateView } from "../src";

describe("accessible shared foundation", () => {
  it("renders a skip link, navigation landmark and main landmark", () => {
    const html = renderToStaticMarkup(
      <ApplicationShell
        appName="سامانه"
        navigation={[{ href: "/", label: "خانه" }]}
        navigationLabel="ناوبری اصلی"
        skipToContentLabel="رفتن به محتوا"
        variant="trader"
      >
        <StateView description="شرح" kind="empty" title="عنوان" />
      </ApplicationShell>,
    );

    expect(html).toContain('href="#main-content"');
    expect(html).toContain("<nav");
    expect(html).toContain("<main");
    expect(html).toContain('role="status"');
  });
});
