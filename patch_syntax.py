import re
with open("/Users/mac/Desktop/TBI/ui/index.html", "r") as f:
    content = f.read()

content = content.replace("""    } else {
      $("#tillBtn").style.display="inline-block";
      $("#genBtn").style.display="none";
    } else {""", """    } else {""")

with open("/Users/mac/Desktop/TBI/ui/index.html", "w") as f:
    f.write(content)
