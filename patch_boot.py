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
      // But keep the "The day so far" header visible because it has the generate button
      const daySection = $("#tillBtn").closest("section");
      daySection.style.display="block";
      daySection.querySelector("#figs").innerHTML = "<p style='padding: 2rem 0; color: var(--ink-2);'>The shop is currently empty. Run the data generator to see Sonnabon in action.</p>";
      daySection.querySelector("#bars").style.display="none";
      daySection.querySelector("#dayNote").textContent="";
      
      // Hide the pulse stats
      document.querySelector(".pulse").style.display="none";
      
      return; // Skip rendering the rest of the empty data
    } else {
      $("#tillBtn").style.display="inline-block";
      $("#genBtn").style.display="none";
      document.querySelectorAll(".card").forEach(c => c.style.display="block");
      document.querySelector(".pulse").style.display="flex";
    }
"""

content = content.replace(
"""    const o=await api("/api/overview");
    if(o.shop && o.shop.bills === 0) {
      $("#tillBtn").style.display="none";
      $("#genBtn").style.display="inline-block";
    } else {
      $("#tillBtn").style.display="inline-block";
      $("#genBtn").style.display="none";
    }""", new_boot)

with open("/Users/mac/Desktop/TBI/ui/index.html", "w") as f:
    f.write(content)
