# 🛡️ Albayan CCTV Lab Screen Monitor (4 Computers)

ലാബിലെ 4 കമ്പ്യൂട്ടറുകൾ (`albayan 1`, `albayan 2`, `albayan 3`, `albayan 4`) ഒരു യഥാർത്ഥ **CCTV സെക്യൂരിറ്റി മോണിറ്റർ (4-Camera Quad Grid)** പോലെ ഒരേസമയം നിരീക്ഷിക്കാനുള്ള സമ്പൂർണ്ണ സിസ്റ്റം.

GitHub Repo: [https://github.com/bayan313/cctv](https://github.com/bayan313/cctv)  
Web Portal Password: **`albayan@2026`**

---

## 🌟 പ്രധാന ഫീച്ചറുകൾ (Key Features)

1. **CCTV Quad-View Screen (2x2 Grid):**
   - യഥാർത്ഥ CCTV കൺട്രോൾ റൂം പോലെ 4 കമ്പ്യൂട്ടറുകളുടെയും സ്ക്രീനുകൾ ഒരൊറ്റ പേജിൽ ലൈവായി കാണാം (CAM 1, CAM 2, CAM 3, CAM 4).
   - ഏത് ക്യാമറയിലും ക്ലിക്ക് ചെയ്ത് ഫുൾ സ്ക്രീൻ (Full-Screen Zoom) ആക്കാം.

2. **5-മിനിറ്റ് സ്നാപ്പ്ഷോട്ട് & CCTV ടൈംലൈൻ റീൽ (No Black Screens!):**
   - ഓരോ 5 മിനിറ്റിലും ഉയർന്ന നിലവാരമുള്ള സ്ക്രീൻഷോട്ടുകൾ എടുത്ത് സേവ് ചെയ്യുന്നു.
   - പ്രത്യേക വീഡിയോ ഫയലുകൾ ഒരോന്നായി ഡൗൺലോഡ് ചെയ്യേണ്ടതില്ല!
   - CCTV മോണിറ്ററിന് താഴെയുള്ള **Timeline Scrubber / "Play Day's Reel"** ബട്ടൺ ക്ലിക്ക് ചെയ്താൽ, അന്നേ ദിവസം മുഴുവൻ കുട്ടികൾ കമ്പ്യൂട്ടറിൽ എന്താണ് ചെയ്തതെന്ന് നിമിഷങ്ങൾക്കുള്ളിൽ CCTV ടൈംലാപ്സ് വീഡിയോ പോലെ കണ്ട് തീർക്കാം!

3. **ഓട്ടോമാറ്റിക് PC Naming (`albayan 1, 2, 3, 4`):**
   - ഓരോ കമ്പ്യൂട്ടറിലും `INSTALL_CLIENT.bat` ഡബിൾ ക്ലിക്ക് ചെയ്താൽ മതി. ഒന്നാമത്തേത് `albayan 1`, രണ്ടാമത്തേത് `albayan 2`, മൂന്നാമത്തേത് `albayan 3`, നാലാമത്തേത് `albayan 4` എന്ന് ഓട്ടോമാറ്റിക് ആയി രജിസ്റ്റർ ആകും.

4. **10 Seconds Delay & Overt Popup:**
   - കമ്പ്യൂട്ടർ ഓൺ ആയി 10 സെക്കൻഡ് കഴിയുമ്പോൾ സ്ക്രീനിൽ അറിയിപ്പ് വരും:  
     `⚠️ [ALBAYAN 1] CCTV MONITORING ACTIVE: This computer is under screen monitoring.`

5. **24-Hour Rolling Auto-Delete:**
   - 24 മണിക്കൂർ കഴിഞ്ഞ പഴയ സ്ക്രീൻഷോട്ടുകൾ സെർവർ സ്വയം ഡിലീറ്റ് ചെയ്യും. സ്റ്റോറേജ് ഒരിക്കലും ഫുള്ളാവില്ല!

6. **Safe Auto-Update from GitHub:**
   - ഭാവിയിൽ മാറ്റങ്ങൾ വരുത്തി GitHub-ലേക്ക് പുഷ് ചെയ്താൽ സോഫ്റ്റ്‌വെയർ തനിയെ അപ്‌ഡേറ്റ് ആകും.

7. **Telegram Bot Integration:**
   - [@my_library_data_bot](https://t.me/my_library_data_bot) വഴി `/cam1`, `/cam2`, `/cam3`, `/cam4` എന്ന് അയച്ചാൽ ആ കമ്പ്യൂട്ടറിലെ ഏറ്റവും പുതിയ ഫോട്ടോ ടെലിഗ്രാമിൽ ഉടനടി ലഭിക്കും!

---

## 🚀 ഇൻസ്റ്റാളേഷൻ (Quick Setup)

### കമ്പ്യൂട്ടർ 1 (Main PC & Server):
1. [**`RUN_SERVER.bat`**](file:///c:/Users/AL-BAYAN/Documents/albayan%20web/study-monitor/RUN_SERVER.bat) ഡബിൾ ക്ലിക്ക് ചെയ്യുക (സെർവർ റൺ ആകും).
2. [**`INSTALL_CLIENT.bat`**](file:///c:/Users/AL-BAYAN/Documents/albayan%20web/study-monitor/INSTALL_CLIENT.bat) ഡബിൾ ക്ലിക്ക് ചെയ്യുക.

### ബാക്കി കമ്പ്യൂട്ടറുകളിൽ (PC 2, 3, 4):
* ബ്രൗസറിൽ `http://192.168.1.3:8899` തുറക്കുക.
* പാസ്‌വേഡ്: `albayan@2026` നൽകുക.
* മുകളിലുള്ള **"Download 1-Click Installer"** ബട്ടൺ ക്ലിക്ക് ചെയ്ത് ഡൗൺലോഡ് ചെയ്ത ഫയൽ ഡബിൾ ക്ലിക്ക് ചെയ്യുക!
*(തനിയെ ആ കമ്പ്യൂട്ടർ അടുത്ത നമ്പറായി സെറ്റപ്പ് ആയിക്കോളും).*

---

## 🔑 വെബ് പോർട്ടൽ
* **URL:** `http://localhost:8899` (മൊബൈലിൽ: `http://192.168.1.3:8899`)
* **Password:** `albayan@2026`
