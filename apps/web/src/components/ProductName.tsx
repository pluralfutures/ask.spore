// The product name as users see it: "Mycelium" in the Mycelium Gastronomy logo typeface
// (Poppins 700), then "SporeBot" in the app's own type. Plain text for assistive tech.
export function ProductName() {
  return (
    <>
      <span className="font-brand font-strong">Mycelium</span> SporeBot
    </>
  );
}
