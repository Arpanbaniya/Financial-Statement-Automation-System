import Link from "next/link";
import { ApiHealth } from "./components/api-health";

export default function HomePage() {
  return (
    <main className="landing">
      <section className="hero">
        <div className="hero__copy">
          <p className="eyebrow">A clearer view of the numbers</p>
          <h1>
            Financial statements you can <em>trace.</em>
          </h1>
          <p className="description">
            Turn a trial balance into financial statements. Review account
            mappings, reconcile the figures, and explore the results with clear
            charts and an Excel report.
          </p>
          <div className="actions">
            <Link className="button button--primary" href="/signup">
              Create a workspace <span aria-hidden="true">↗</span>
            </Link>
            <Link
              className="button button--secondary"
              href="/dashboard/trial-balance"
            >
              Generate statements
            </Link>
          </div>
          <p className="hero__note">
            PDF, XLSX and CSV · Private uploads · Excel exports
          </p>
        </div>
        <div
          className="hero__preview"
          aria-label="Example source linked statement"
        >
          <div className="preview__toolbar">
            <span className="preview__dots" aria-hidden="true">
              ● ● ●
            </span>
            <span>Income statement / FY 2025</span>
            <span className="preview__status">Reviewed</span>
          </div>
          <div className="preview__body">
            <div className="preview__heading">
              <div>
                <span className="eyebrow">Example statement</span>
                <h2>How the year adds up</h2>
              </div>
              <span>USD · actuals</span>
            </div>
            <div className="preview__row">
              <span>Revenue</span>
              <strong>1,000</strong>
              <small>Source B2</small>
            </div>
            <div className="preview__row">
              <span>Cost of sales</span>
              <strong>(600)</strong>
              <small>Source B3</small>
            </div>
            <div className="preview__row preview__row--total">
              <span>Gross profit</span>
              <strong>400</strong>
              <small>Checked ✓</small>
            </div>
            <div className="preview__insight">
              <span className="preview__insight-icon">↗</span>
              <div>
                <strong>40% gross margin</strong>
                <p>Calculated from the accepted source figures above.</p>
              </div>
            </div>
          </div>
        </div>
      </section>
      <section className="landing-steps" aria-label="How it works">
        <div>
          <span>01 / Upload</span>
          <h2>Start with the original</h2>
          <p>
            Keep the file private and every extracted figure linked to its
            source.
          </p>
        </div>
        <div>
          <span>02 / Review</span>
          <h2>Check what matters</h2>
          <p>
            Confirm dates, units and mappings. Uncertain values stay in a review
            queue.
          </p>
        </div>
        <div>
          <span>03 / Analyze</span>
          <h2>See the full picture</h2>
          <p>
            Explore validation, ratios and working capital, then export to
            Excel.
          </p>
        </div>
      </section>
      <div className="landing__health">
        <ApiHealth />
      </div>
    </main>
  );
}
