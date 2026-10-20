import { defineControlUiPlugin } from "openclaw/plugin-sdk/control-ui";
import { createFeatureClient } from "openclaw/plugin-sdk/feature-contract";
import { contract } from "./contract.js";
import "./control-ui.css";

export default defineControlUiPlugin({
  id: contract.pluginId,
  activate(host) {
    host.ui.registerNavigation({
      id: "discovery",
      label: "ACCE Optimizer",
      page: { id: "discovery" },
      icon: "refreshCw",
      order: 80,
    });

    host.ui.registerPage({
      id: "discovery",
      label: "ACCE Optimizer",
      mount(container, context) {
        const feature = createFeatureClient(contract, context.host);
        const section = document.createElement("section");
        section.className = "acce-discovery-page";

        const heading = document.createElement("h1");
        heading.textContent = "ACCE Optimizer";
        const intro = document.createElement("p");
        intro.textContent =
          "Discover configured Ollama models on first startup, then recalibrate whenever you choose. Existing inventories are refreshed rather than duplicated.";
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Recalibrate discovery now";
        const status = document.createElement("output");
        status.className = "acce-discovery-status";
        status.setAttribute("role", "status");
        status.setAttribute("aria-live", "polite");
        status.textContent = "Ready. Discovery runs against the configured Ollama URL.";
        const note = document.createElement("p");
        note.className = "acce-discovery-note";
        note.textContent =
          "Configure the Ollama URL and first-start behavior in OpenClaw → Settings → Plugins → ACCE Optimizer. Production model routing remains disabled.";

        let disposed = false;
        const updateAvailability = () => {
          button.disabled = !context.host.connection.connected ||
            !context.host.connection.canWrite || disposed;
          if (!context.host.connection.canWrite) {
            status.textContent = "Operator write permission is required to recalibrate discovery.";
          }
        };
        const unsubscribe = context.host.subscribe(updateAvailability);
        button.disabled = !host.connection.connected || !host.connection.canWrite;

        button.addEventListener("click", async () => {
          if (button.disabled || disposed) return;
          button.disabled = true;
          status.textContent = "Discovery running…";
          try {
            const result = await feature.invoke("refreshDiscovery", {});
            if (disposed || context.signal.aborted) return;
            status.textContent = [
              "Discovery completed",
              `Models discovered: ${result.discovered}`,
              `New records: ${result.added}`,
              `Existing records refreshed: ${result.refreshed}`,
              `Telemetry captured: ${result.telemetryCaptured}`,
              `Telemetry pending: ${result.telemetryPending}`,
              `Production eligible: ${result.productionEligible}`,
            ].join("\n");
          } catch (error) {
            if (!disposed && !context.signal.aborted) {
              status.textContent = error instanceof Error
                ? error.message
                : "Discovery failed. Check Gateway logs and plugin configuration.";
            }
          } finally {
            if (!disposed && !context.signal.aborted) updateAvailability();
          }
        });

        section.append(heading, intro, button, status, note);
        container.append(section);
        return {
          dispose() {
            disposed = true;
            unsubscribe();
            section.remove();
          },
        };
      },
    });
  },
});
