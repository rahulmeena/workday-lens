import Link from "next/link";

export default function AdminPage() {
  return (
    <section className="panel-card admin-retired">
      <p className="section-kicker">Not Available</p>
      <h2>This experience is focused on personal activity insights.</h2>
      <p>
        Workday Lens does not include a separate admin console. Use the main dashboard to review
        how the day unfolded.
      </p>
      <Link href="/">Open personal dashboard</Link>
    </section>
  );
}
