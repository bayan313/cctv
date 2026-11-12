# 🛡️ Albayan CCTV Lab Screen Monitor (4 Computers) - Real Web & Auto-Video Edition

ലാബിലെ 4 കമ്പ്യൂട്ടറുകൾ (`albayan 1`, `albayan 2`, `albayan 3`, `albayan 4`) കമ്പ്യൂട്ടർ ഓൺ ആകുമ്പോൾ തന്നെ:
1. **ഓട്ടോമാറ്റിക്കായി ഓൺ ആയി സ്ക്രീൻ വീഡിയോ റെക്കോർഡ് ചെയ്യാനും** (2-Minute Smooth MP4 Clips).
2. റെക്കോർഡ് ചെയ്ത വീഡിയോകൾ തനിയെ **Telegram-ലേക്ക് അയക്കാനും** ([@my_library_data_bot](https://t.me/my_library_data_bot)).
3. ഒപ്പം ലോകത്തെവിടെയിരുന്നും ഫോണിലൂടെ **CCTV Quad Screen (4 Cameras)** ലൈവായി കാണാനുമുള്ള സമ്പൂർണ്ണ സിസ്റ്റം.

- **GitHub Repo:** [https://github.com/bayan313/cctv](https://github.com/bayan313/cctv)
- **Web Portal Password:** **`albayan@2026`**
- **Telegram Bot:** [@my_library_data_bot](https://t.me/my_library_data_bot)

---

## ⚡ കമ്പ്യൂട്ടർ ഓൺ ആകുമ്പോൾ സംഭവിക്കുന്നത് (Automatic on Computer Boot)

1. **Auto-Start on Boot (10s Delay):**
   - കമ്പ്യൂട്ടർ ഓൺ ആകുമ്പോൾ വിൻഡോസ് സ്റ്റാർട്ടപ്പ് വഴി സോഫ്റ്റ്‌വെയർ തനിയെ ബാക്ക്ഗ്രൗണ്ടിൽ റൺ ആകും.
   - 10 സെക്കൻഡിനു ശേഷം സ്ക്രീനിൽ അറിയിപ്പ് വരും:  
     `⚠️ [ALBAYAN 1] CCTV MONITORING ACTIVE: Screen recording and monitoring is active.`

2. **തത്സമയം Telegram Alert:**
   - കമ്പ്യൂട്ടർ ഓൺ ആയ ഉടൻ അഡ്മിൻ്റെ ടെലിഗ്രാമിലേക്ക് അറിയിപ്പ് എത്തും:  
     `🚨 [ALBAYAN 1] Computer Turned ON! Screen video recording & CCTV monitoring started.`

3. **ഓട്ടോമാറ്റിക് വീഡിയോ റെക്കോർഡിംഗ് & Telegram ഡെലിവറി:**
   - ഓരോ 2 മിനിറ്റിലും 10 FPS നിലവാരമുള്ള സ്മൂത്ത് MP4 വീഡിയോ ക്ലിപ്പ് തനിയെ റെക്കോർഡ് ചെയ്യപ്പെടും.
   - ക്ലിപ്പ് തീരുന്ന ഉടൻ അത് തനിയെ അഡ്മിൻ്റെ ടെലിഗ്രാമിലേക്ക് അയക്കപ്പെടും!

4. **Real Web CCTV Quad-Grid ലൈവ് സ്ട്രീം:**
   - ഒപ്പം 4 ക്യാമറകളും ഒരൊറ്റ സ്ക്രീനിൽ ലൈവായി (CCTV DVR പോലെ) റിയൽ വെബിൽ അപ്‌ഡേറ്റ് ആയിക്കൊണ്ടിരിക്കും.

---

## 📱 Telegram Bot കമാൻഡുകൾ (@my_library_data_bot)

* `/status` - എല്ലാ കമ്പ്യൂട്ടറുകളുടെയും ലൈവ് സ്റ്റാറ്റസ് അറിയാൻ.
* `/cam1`, `/cam2`, `/cam3`, `/cam4` - ആ കമ്പ്യൂട്ടറിലെ ഏറ്റവും പുതിയ ഫോട്ടോ ഉടനടി ലഭിക്കാൻ.
* `/showvideos` - പുതിയ വീഡിയോ ക്ലിപ്പുകൾ തനിയെ ടെലിഗ്രാമിൽ അയക്കുന്നത് ഓൺ ആക്കാൻ.
* `/hidevideos` - വീഡിയോകൾ ടെലിഗ്രാമിൽ വരുന്നത് താൽക്കാലികമായി നിർത്താൻ (സെർവറിൽ മാത്രം സേവ് ആകും).
* `/link` - റിയൽ വെബ് CCTV പോർട്ടൽ ലിങ്ക് ലഭിക്കാൻ.

---

## 🚀 ഇൻസ്റ്റാളേഷൻ & റൺ ചെയ്യൽ

### കമ്പ്യൂട്ടർ 1 (Main PC & Server):
1. **ഓട്ടോ-സ്റ്റാർട്ട് സെറ്റപ്പ് ചെയ്യാൻ:**
   - `python setup_startup.py` റൺ ചെയ്യുക (ഇതിനകം കമ്പ്യൂട്ടറിൽ ഓട്ടോമാറ്റിക് സ്റ്റാർട്ടപ്പ് സെറ്റ് ചെയ്തിട്ടുണ്ട്).
2. **സെർവർ റൺ ചെയ്യാൻ:**
   - [**`RUN_SERVER.bat`**](file:///c:/Users/AL-BAYAN/Documents/degree/bcom/study-monitor/RUN_SERVER.bat) ഡബിൾ ക്ലിക്ക് ചെയ്യുക.

### ബാക്കി കമ്പ്യൂട്ടറുകളിൽ (PC 2, 3, 4):
* ബ്രൗസറിൽ നിങ്ങളുടെ **Real Web Link** തുറക്കുക.
* പാസ്‌വേഡ്: **`albayan@2026`**
* മുകളിലുള്ള **"Download 1-Click Installer"** ക്ലിക്ക് ചെയ്ത് ഡൗൺലോഡ് ചെയ്ത ഫയൽ ഡബിൾ ക്ലിക്ക് ചെയ്യുക!
*(തനിയെ ആ കമ്പ്യൂട്ടറും സ്റ്റാർട്ടപ്പിൽ സെറ്റ് ആയി വീഡിയോകളും സ്ക്രീനും അയച്ചു തുടങ്ങും).*
