import re
with open("/Users/mac/Desktop/TBI/ui/index.html", "r") as f:
    content = f.read()

new_boot = """
    const o=await api("/api/overview");
    if(o.shop && o.shop.bills === 0) {
      $("#tillBtn").style.display="none";
      $("#genBtn").style.display="inline-block";
      
      // Hide all the cards that don't make sense empty
      document.querySelectorAll(".card").forEach(c => c.style.display="none");
      
      // Hide navigation, prompt, and pulse stats
      document.querySelector("nav").style.display="none";
      document.querySelector(".brief").style.display="none";
      document.querySelector(".hints").style.display="none";
      document.querySelector(".pulse").style.display="none";
      
      // But keep the "The day so far" header visible because it has the generate button
      // Let's rewrite its title to "Welcome to Sonnabon"
      const daySection = $("#tillBtn").closest("section");
      daySection.style.display="block";
      daySection.querySelector("h2").textContent="Awaiting Data";
      daySection.querySelector("#figs").innerHTML = "<p style='padding: 2rem 0; color: var(--ink-2); font-size: 1.1rem;'>The shop is currently empty. Start by feeding it receipts, or run the data generator to see Sonnabon in action.</p>";
      daySection.querySelector("#bars").style.display="none";
      daySection.querySelector("#dayNote").textContent="";
      
      return; // Skip rendering the rest of the empty data
    } else {
      $("#tillBtn").style.display="inline-block";
      $("#genBtn").style.display="none";
    }
"""

# Find my previous injection and replace it
content = re.sub(r'const o=await api\("/api/overview"\);\n    if\(o\.shop && o\.shop\.bills === 0\) \{.*?\n    \}', new_boot.strip(), content, flags=re.DOTALL)

with open("/Users/mac/Desktop/TBI/ui/index.html", "w") as f:
    f.write(content)
