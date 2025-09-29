{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NIFTY Market Tracker</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">

<style>
/* --- Reset & Base --- */
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Inter',sans-serif;transition: background 0.5s, color 0.5s;}
.container{max-width:1400px;margin:auto;padding:15px;}

/* --- Light/Dark Mode --- */
body.light-mode{background:#f4f6f8;color:#333;}
body.dark-mode{background:#121212;color:#e9ecef;}

/* --- Header --- */
.header{display:flex;align-items:center;justify-content:space-between;background:#fff;padding:15px 25px;border-radius:10px;box-shadow:0 4px 12px rgba(0,0,0,0.1);margin-bottom:20px;}
body.dark-mode .header{background:#1e1e1e;box-shadow:0 4px 12px rgba(0,0,0,0.3);}
.header .logo{display:flex;align-items:center;}
.header .logo img{width:40px;height:40px;margin-right:12px;}
.header .title{font-size:1.6rem;font-weight:700;color:#2c3e50;}
body.dark-mode .header .title{color:#fff;}

/* --- Controls --- */
.controls{display:flex;flex-wrap:wrap;gap:15px;align-items:center;background:#fff;padding:20px;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.05);margin-bottom:25px;}
body.dark-mode .controls{background:#1e1e1e;box-shadow:0 4px 20px rgba(0,0,0,0.3);}
.controls select,.controls button{padding:10px 16px;border:1px solid #ccc;border-radius:8px;font-size:14px;cursor:pointer;}
body.dark-mode .controls select{border:1px solid #555;color:#fff;background:#2c2c2c;}
.controls .btn-submit{background:#5a67d8;color:white;border:none;}
.controls .btn-update{background:#38a169;color:white;border:none;}
.controls .btn-reset{background:#e53e3e;color:white;border:none;}

/* --- Summary Cards --- */
.summary-cards{display:flex;flex-wrap:wrap;gap:15px;margin-bottom:25px;}
.summary-card{flex:1 1 200px;background:#fff;border-radius:12px;padding:15px;box-shadow:0 4px 10px rgba(0,0,0,0.05);text-align:center;font-weight:600;font-size:14px;}
body.dark-mode .summary-card{background:#1e1e1e;box-shadow:0 4px 10px rgba(0,0,0,0.3);}
.summary-card.bullish{border:2px solid #38a169;color:#38a169;}
.summary-card.bearish{border:2px solid #e53e3e;color:#e53e3e;}
.summary-card.neutral{border:2px solid #718096;color:#2d3748;}
.progress{width:100%;background:#edf2f7;border-radius:8px;height:8px;margin-top:8px;overflow:hidden;}
.progress-bar{height:100%;border-radius:8px;}
.progress-bar.bullish{background:#38a169;}
.progress-bar.bearish{background:#e53e3e;}
.progress-bar.neutral{background:#718096;}

/* --- Trade Snippets --- */
.snippets-wrapper{display:flex;flex-wrap:wrap;gap:15px;margin-bottom:30px;}
.snippet{flex:1 1 200px;background:#fff;border-radius:12px;padding:15px;box-shadow:0 4px 10px rgba(0,0,0,0.05);text-align:center;font-weight:600;font-size:14px;}
body.dark-mode .snippet{background:#1e1e1e;box-shadow:0 4px 10px rgba(0,0,0,0.3);}
.snippet.bullish{border:2px solid #38a169;color:#38a169;}
.snippet.bearish{border:2px solid #e53e3e;color:#e53e3e;}
.snippet .day-label{font-size:0.85rem;margin-bottom:6px;}
.snippet .trend{font-size:1.1rem;margin-bottom:4px;}
.snippet .trade{font-weight:500;}

/* --- Table --- */
table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.05);margin-bottom:20px;}
body.dark-mode table{background:#1e1e1e;box-shadow:0 4px 20px rgba(0,0,0,0.3);}
thead{background:linear-gradient(135deg,#5a67d8,#7b2ff7);color:#fff;}
th,td{padding:10px;text-align:center;font-size:14px;}
tr:nth-child(even){background:#f8f9fa;}
body.dark-mode tr:nth-child(even){background:#2c2c2c;}
tr:hover{background:#edf2ff;}
body.dark-mode tr:hover{background:#333;}
.points-positive{color:#38a169;font-weight:bold;}
.points-negative{color:#e53e3e;font-weight:bold;}
.bullish{color:#38a169;font-weight:bold;}
.bearish{color:#e53e3e;font-weight:bold;}
.neutral{color:#718096;font-weight:bold;}

/* --- Accordion Buttons & Content --- */
.btn-toggle {background:#f3f4f6;border:1px solid #ccc;border-radius:6px;padding:4px 10px;font-size:13px;cursor:pointer;transition:all 0.2s ease;}
.btn-toggle:hover { background:#e2e8f0; }
.btn-toggle.active { background:linear-gradient(135deg,#7b2ff7,#5a67d8); color:white;font-weight:600;border:none; box-shadow:0 2px 6px rgba(0,0,0,0.2);}
.accordion-content{display:none;background:#f9fafb;}
body.dark-mode .accordion-content{background:#1e1e1e;}
.accordion-content.active{display:table-row-group;}
.accordion-header{font-weight:700;padding:10px;border-radius:8px 8px 0 0;color:#fff;margin-bottom:5px;}
.accordion-header.hourly{background:linear-gradient(135deg,#5a67d8,#7b2ff7);}
.accordion-header.m30{background:linear-gradient(135deg,#38a169,#2f855a);}
</style>
</head>

<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="logo">
      <img src="https://img.icons8.com/color/48/000000/stock-market.png" alt="Logo"/>
      <div class="title">NIFTY Market Tracker</div>
    </div>
    <button id="themeToggle">🌙 Dark Mode</button>
  </div>

  <!-- Controls -->
  <div class="controls">
    <form method="get" style="display:flex;gap:10px;">
       <select name="filter">
         <option value="all" {% if filter_option == 'all' %}selected{% endif %}>All</option>
         <option value="today" {% if filter_option == 'today' %}selected{% endif %}>Today</option>
         <option value="week" {% if filter_option == 'week' %}selected{% endif %}>This Week</option>
         <option value="month" {% if filter_option == 'month' %}selected{% endif %}>This Month</option>
       </select>
       <button type="submit" class="btn-submit">⚡ Apply</button>
    </form>
    <form method="post">{% csrf_token %}
      <button type="submit" name="update_data" class="btn-update">🔄 Update</button>
    </form>
    <button onclick="resetAll()" class="btn-reset">🗑️ Reset</button>
  </div>

  <!-- Summary Cards -->
  <div class="summary-cards">
    <div class="summary-card bullish">📈 Bullish Days: {{ bullish_percent }}%
      <div class="progress"><div class="progress-bar bullish" style="width:{{ bullish_percent }}%"></div></div>
    </div>
    <div class="summary-card bearish">📉 Bearish Days: {{ bearish_percent }}%
      <div class="progress"><div class="progress-bar bearish" style="width:{{ bearish_percent }}%"></div></div>
    </div>
    <div class="summary-card neutral">⚖️ Neutral Days: {{ neutral_percent }}%
      <div class="progress"><div class="progress-bar neutral" style="width:{{ neutral_percent }}%"></div></div>
    </div>
  </div>

  <!-- Trade Snippets -->
  <div class="snippets-wrapper">
    {% for label,snippet in snippets.items %}
    <div class="snippet {% if snippet.trend == 'Bullish' %}bullish{% else %}bearish{% endif %}">
      <div class="day-label">{{ label }}</div>
      <div class="trend">{% if snippet.trend == 'Bullish' %}📈 Bullish{% else %}📉 Bearish{% endif %}</div>
      <div class="trade">Take {{ snippet.trade }}</div>
    </div>
    {% endfor %}
  </div>

  <!-- Records Table -->
  <table>
    <thead>
      <tr>
        <th>S.No</th><th>Date</th><th>Open</th><th>Low</th><th>High</th><th>Close</th>
        <th>Points</th><th>Decision</th><th>FII Net</th><th>DII Net</th>
        <th>Bias</th><th>More</th><th>PCR</th>
      </tr>
    </thead>
    <tbody>
      {% for rec in records %}
      <tr>
        <td>{{ forloop.counter0|add:records.start_index }}</td>
        <td>{{ rec.date|date:"D, M d, Y" }}</td>
        <td>{{ rec.nifty_open }}</td>
        <td>{{ rec.nifty_low }}</td>
        <td>{{ rec.nifty_high }}</td>
        <td>{{ rec.nifty_close }}</td>
        <td class="{% if rec.points >= '0' %}points-positive{% else %}points-negative{% endif %}">{% if rec.points >= '0' %}+{% endif %}{{ rec.points }}</td>
        <td class="{% if rec.calculated_decision == 'Bullish' %}bullish{% elif rec.calculated_decision == 'Bearish' %}bearish{% else %}neutral{% endif %}">
          {% if rec.calculated_decision == 'Bullish' %}📈{% elif rec.calculated_decision == 'Bearish' %}📉{% else %}⚖️{% endif %} {{ rec.calculated_decision }}
        </td>
        <td>{{ rec.fii_net }}</td>
        <td>{{ rec.dii_net }}</td>
        <td>{{ rec.bias_label }}</td>
        <td>
          <button type="button" class="btn-toggle" onclick="toggleAccordion('hourly-{{ rec.id }}', this)">⏰ Hourly</button>
          <button type="button" class="btn-toggle" onclick="toggleAccordion('m30-{{ rec.id }}', this)">⏱ 30m</button>
        </td>
        <td>{{ rec.pcr }}</td>
      </tr>

      <!-- Hourly Accordion -->
      <tbody id="hourly-{{ rec.id }}" class="accordion-content hourly">
        <tr><td colspan="13">
          <table>
            <thead><tr><th>Hour</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Points</th><th>Decision</th></tr></thead>
            <tbody>
              {% for hr in rec.hourly_set_calculated %}
              <tr>
                <td>{{ hr.hour|time:"H:i" }}</td>
                <td>{{ hr.nifty_open }}</td>
                <td>{{ hr.nifty_high }}</td>
                <td>{{ hr.nifty_low }}</td>
                <td>{{ hr.nifty_close }}</td>
                <td class="{% if hr.points >= '0' %}points-positive{% else %}points-negative{% endif %}">{% if hr.points >= '0' %}+{% endif %}{{ hr.points }}</td>
                <td class="{% if hr.calculated_decision == 'Bullish' %}bullish{% elif hr.calculated_decision == 'Bearish' %}bearish{% else %}neutral{% endif %}">{{ hr.calculated_decision }}</td>
              </tr>
              {% empty %}<tr><td colspan="7">No hourly data</td></tr>{% endfor %}
            </tbody>
          </table>
        </td></tr>
      </tbody>

      <!-- 30m Accordion -->
      <tbody id="m30-{{ rec.id }}" class="accordion-content m30">
        <tr><td colspan="13">
          <table>
            <thead><tr><th>Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Points</th><th>Decision</th></tr></thead>
            <tbody>
              {% for m30 in rec.m30_set_calculated %}
              <tr>
                <td>{{ m30.hour|time:"H:i" }}</td>
                <td>{{ m30.nifty_open }}</td>
                <td>{{ m30.nifty_high }}</td>
                <td>{{ m30.nifty_low }}</td>
                <td>{{ m30.nifty_close }}</td>
                <td class="{% if m30.points >= 0 %}points-positive{% else %}points-negative{% endif %}">{% if m30.points >= 0 %}+{% endif %}{{ m30.points }}</td>
                <td class="{% if m30.calculated_decision == 'Bullish' %}bullish{% elif m30.calculated_decision == 'Bearish' %}bearish{% else %}neutral{% endif %}">{{ m30.calculated_decision }}</td>
              </tr>
              {% empty %}<tr><td colspan="7">No 30m data</td></tr>{% endfor %}
            </tbody>
          </table>
        </td></tr>
      </tbody>

      {% endfor %}
    </tbody>
  </table>
</div>

<script>
function resetAll(){ window.location.href="{% url 'record_list' %}"; }

function toggleAccordion(id, btn){
  const target=document.getElementById(id);
  const active=target.style.display==='table-row-group';
  target.style.display=active?'none':'table-row-group';
  btn.classList.toggle('active',!active);
}

/* --- Dark/Light Mode --- */
const body=document.body;
const themeBtn=document.getElementById('themeToggle');
let savedTheme=localStorage.getItem('theme')||'light';
setTheme(savedTheme);
themeBtn.addEventListener('click',()=>{setTheme(body.classList.contains('light-mode')?'dark':'light');});
function setTheme(mode){
  body.classList.remove('light-mode','dark-mode');
  body.classList.add(mode+'-mode');
  themeBtn.innerText=(mode==='dark')?'☀️ Light Mode':'🌙 Dark Mode';
  localStorage.setItem('theme',mode);
}
</script>
</body>
</html>
