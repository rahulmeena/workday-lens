import type { Metadata } from "next";

import "./globals.css";
import { DEMO_MODE } from "../lib/config";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Workday Lens",
  description: "A personal activity intelligence dashboard for understanding how your time was spent.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          {DEMO_MODE && <div className="demo-notice">Synthetic demo · fictional activity · no live capture</div>}
          <main className="app-shell">
            <section className="app-content">{children}</section>
          </main>
        </Providers>
      </body>
    </html>
  );
}
