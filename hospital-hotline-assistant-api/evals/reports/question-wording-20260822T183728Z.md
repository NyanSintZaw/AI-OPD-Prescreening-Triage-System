# Question wording review — 20260822T183728Z

- model: vertexai:gemini-3.1-flash-lite
- questions rendered: 470 (every kind except measurement; confirm = one per critical finding)

- **th**: rewording used 225/235, refused → template 10, errors 0
  - refusal reasons: {'not_a_question': 1, 'not_yes_no': 3, 'missing': 6}
- **en**: rewording used 220/235, refused → template 12, errors 0
  - refusal reasons: {'validator': 5, 'question_count': 5, 'too_long': 1, 'missing': 2}

## Sheet

| id | kind | lang | template | model's rewording | verdict |
|---|---|---|---|---|---|
| uq_intake | intake | th | วันนี้มีอาการอะไรถึงมาพบเราคะ | วันนี้มีอาการอะไรที่ทำให้รู้สึกไม่สบายตัวจนต้องมาพบเราคะ | used |
| uq_intake | intake | en | What symptoms brought you in today? | What brings you in to see us today? | used |
| uq_age | age | th | ขออนุญาตสอบถามอายุของคุณ (หรือผู้ป่วย) ได้ไหมคะ | ไม่ทราบว่าตอนนี้คุณอายุเท่าไหร่คะ | used |
| uq_age | age | en | May I ask how old you are (or the patient's age)? | Could you please tell me your age? | used |
| uq_gender | gender | th | ขออนุญาตสอบถามเพศของคุณ เป็นเพศชายหรือเพศหญิงคะ เพื่อให้ถามเฉพาะคำถามที่เกี่ยวข้องกับคุณ หากไม่สะดวกตอบ ข้ามได้ค่ะ | ขออนุญาตสอบถามเพศของคุณ เพื่อให้ข้อมูลที่เหมาะสมกับคุณนะคะ | used |
| uq_gender | gender | en | May I ask your sex — male or female? It helps me ask only the questions that apply to you. You may skip this if you prefer. | Could you please tell me your sex? This helps me ask the right questions for you. | used |
| uq_breathing | red_flag | th | ตอนนี้คุณหายใจลำบากหรือหายใจเหนื่อยไหมคะ | ตอนนี้คุณรู้สึกหายใจเหนื่อยหรือหายใจลำบากบ้างไหมคะ | used |
| uq_breathing | red_flag | en | Right now, are you having any trouble breathing? | Are you having any trouble catching your breath right now? | used |
| gen_onset | slot | th | อาการนี้เริ่มเป็นเมื่อไหร่คะ | อาการที่คุณเล่ามานี้ เริ่มมีอาการตั้งแต่เมื่อไหร่คะ | used |
| gen_onset | slot | en | When did this start? | When did you first start feeling this way? | used |
| gen_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| gen_duration | slot | en | How long has it been going on? | How long have you been feeling this way? | used |
| gen_character | slot | th | ช่วยเล่าลักษณะอาการให้ฟังหน่อยได้ไหมคะ | อาการที่เป็นอยู่มีลักษณะอย่างไรบ้างคะ เช่น ปวดตื้อ ๆ ปวดแปลบ หรือรู้สึกแน่น ๆ คะ | used |
| gen_character | slot | en | Can you describe what it feels like? | Could you tell me a bit more about how that feels? | used |
| gen_severity | scale | th | ถ้าให้คะแนน 0 ถึง 10 ตอนนี้อาการรุนแรงประมาณเท่าไหร่คะ | ถ้าให้คะแนนความรู้สึกจาก 0 ถึง 10 ตอนนี้อาการรุนแรงประมาณเท่าไหร่คะ | used |
| gen_severity | scale | en | On a scale of 0 to 10, how bad is it right now? | On a scale of 0 to 10, how would you rate your pain right now? | used |
| gen_associated | associated | th | มีไข้ อาเจียน หรือถ่ายเหลวร่วมด้วยไหมคะ | ตอนนี้มีอาการไข้ขึ้น อาเจียน หรือถ่ายเหลวบ้างไหมคะ | used |
| gen_associated | associated | en | Do you also have fever, vomiting, or diarrhea? | Are you also dealing with a fever, throwing up, or loose stools? | used |
| gen_bleeding | red_flag | th | มีเลือดออกมากจนห้ามไม่หยุดไหมคะ | ตอนนี้มีเลือดไหลออกมามากจนห้ามไม่อยู่บ้างไหมคะ | used |
| gen_bleeding | red_flag | en | Do you have heavy bleeding that won't stop? | Are you currently experiencing any heavy bleeding that you cannot get to stop? | used |
| gen_syncope_confusion | red_flag | th | มีวูบหมดสติ หรือรู้สึกสับสน ซึมผิดปกติไหมคะ | มีอาการวูบหมดสติไปบ้างไหมคะ หรือว่าดูซึมลง พูดจาสับสนไม่ค่อยรู้เรื่องบ้างหรือเปล่า | used |
| gen_syncope_confusion | red_flag | en | Have you fainted, or become newly confused or unusually drowsy? | Have you felt like you might faint, or have you been feeling unusually sleepy or confused in the last day? | used |
| gen_severe_pain | red_flag | th | อาการปวดรุนแรงมากจนทนไม่ไหวเลยไหมคะ | ตอนนี้คุณรู้สึกปวดรุนแรงมากจนทนไม่ไหว หรือปวดที่สุดในชีวิตเลยไหมคะ | used |
| gen_severe_pain | red_flag | en | Is your pain so severe that you cannot bear it? | Is your pain so severe that you cannot bear it, or is it the worst pain you have ever felt? | refused: validator |
| cp_radiating | red_flag | th | อาการเจ็บร้าวไปที่คอ กราม ไหล่ หรือแขนไหมคะ | คุณมีอาการเจ็บหน้าอกที่ร้าวไปที่คอ กราม หรือหัวไหล่บ้างไหมคะ | used |
| cp_radiating | red_flag | en | Does the pain spread to your neck, jaw, shoulder, or arm? | Are you feeling any pain that spreads to your neck, jaw, or shoulder? | used |
| cp_diaphoresis | red_flag | th | มีเหงื่อแตก ตัวเย็น หรือใจสั่นร่วมด้วยไหมคะ | ตอนนี้มีอาการเหงื่อแตก ตัวเย็น หรือใจสั่นร่วมด้วยบ้างไหมคะ | used |
| cp_diaphoresis | red_flag | en | Are you sweating a lot, or feeling cold and clammy? | Are you sweating heavily right now, or does your skin feel cold and clammy? | used |
| cp_dyspnea | red_flag | th | หายใจเหนื่อยหรือหายใจลำบากร่วมกับเจ็บหน้าอกไหมคะ | ตอนนี้มีอาการหายใจเหนื่อยหรือหายใจลำบากร่วมกับเจ็บหน้าอกบ้างไหมคะ | used |
| cp_dyspnea | red_flag | en | Are you having trouble breathing along with the chest pain? | Are you feeling short of breath along with that chest pain? | used |
| cp_onset | slot | th | เริ่มเจ็บหน้าอกตั้งแต่เมื่อไหร่ และตอนนั้นกำลังทำอะไรอยู่คะ | คุณเริ่มรู้สึกเจ็บหน้าอกตั้งแต่เมื่อไหร่คะ และตอนนั้นกำลังทำอะไรอยู่ | used |
| cp_onset | slot | en | When did the chest pain start, and were you doing anything at the time? | When did your chest pain begin, and what were you doing when it started? | used |
| cp_duration | slot | th | อาการเจ็บต่อเนื่องนานเกิน 20 นาทีไหมคะ | อาการเจ็บหน้าอกที่เป็นอยู่นี้ นานเกิน 20 นาทีแล้วหรือยังคะ | used |
| cp_duration | slot | en | Has the pain lasted more than 20 minutes continuously? | Has this pain been going on for more than 20 minutes without stopping? | used |
| cp_character | slot | th | ลักษณะเจ็บเป็นแบบไหนคะ เหมือนถูกบีบ ถูกกดทับ หรือแปลบ ๆ | อาการเจ็บหน้าอกของคุณเป็นแบบไหนคะ เหมือนถูกบีบแน่น ๆ ถูกกดทับ หรือรู้สึกแปลบ ๆ คะ | used |
| cp_character | slot | en | What does the pain feel like — squeezing, pressure, or sharp? | Could you describe what the pain feels like? | used |
| cp_severity | scale | th | ให้คะแนนความเจ็บ 0 ถึง 10 ตอนนี้ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกเจ็บปวดมากน้อยแค่ไหนคะ โดยให้คะแนนตั้งแต่ 0 ถึง 10 ค่ะ | used |
| cp_severity | scale | en | On a scale of 0 to 10, how severe is the chest pain? | How would you rate your chest pain on a scale of 0 to 10? | used |
| cp_history | associated | th | มีโรคหัวใจ ความดันสูง เบาหวาน หรือสูบบุหรี่ไหมคะ | คุณมีโรคประจำตัวอย่างโรคหัวใจ ความดันสูง เบาหวาน หรือสูบบุหรี่บ้างไหมคะ | used |
| cp_history | associated | en | Do you have heart disease, high blood pressure, diabetes, or do you smoke? | Do you have any history of heart problems, high blood pressure, or diabetes, or are you a smoker? | used |
| dc_severe_distress | red_flag | th | ตอนนี้พูดเป็นประโยคยาว ๆ ได้ไหมคะ หรือรู้สึกเหนื่อยจนหายใจลำบาก และริมฝีปากหรือปลายนิ้วดูเขียวคล้ำไหมคะ | ตอนนี้คุณพูดเป็นประโยคยาว ๆ ได้ไหมคะ หรือรู้สึกเหนื่อยจนหายใจลำบาก และสังเกตเห็นว่าริมฝีปากหรือปลายนิ้วมีสีเขียวคล้ำบ้างไหมคะ | used |
| dc_severe_distress | red_flag | en | Are you able to talk in full sentences right now, or does it feel like a struggle to breathe? Have your lips or fingertips looked bluish? | Are you able to speak in full sentences, or is it a struggle to breathe? Have you noticed your lips or fingertips turning blue? | refused: question_count |
| dc_hemoptysis | red_flag | th | ไอมีเลือดปนออกมาไหมคะ | เวลาไอออกมา มีเลือดปนออกมาบ้างไหมคะ | used |
| dc_hemoptysis | red_flag | en | Have you coughed up any blood? | Have you noticed any blood when you cough? | used |
| dc_chest_pain | red_flag | th | มีเจ็บหรือแน่นหน้าอกร่วมด้วยไหมคะ | ตอนนี้มีอาการจุกแน่นใต้ลิ้นปี่ หรือเจ็บแน่นหน้าอกบ้างไหมคะ | used |
| dc_chest_pain | red_flag | en | Do you have chest pain or tightness with it? | Are you feeling any pain or tightness in your chest right now? | used |
| dc_fever | red_flag | th | มีไข้ไหมคะ | ตอนนี้คุณมีอาการไข้ขึ้นหรือตัวร้อนบ้างไหมคะ | used |
| dc_fever | red_flag | en | Do you have a fever? | Have you been feeling feverish or had a high temperature lately? | used |
| dc_distress_scale | scale | th | ถ้าให้คะแนน 0 ถึง 10 ตอนนี้หายใจลำบากประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกหายใจเหนื่อยหรือหายใจลำบากมากน้อยแค่ไหนคะ ถ้าให้คะแนนจาก 0 ถึง 10 | used |
| dc_distress_scale | scale | en | On a scale of 0 to 10, how hard is it to breathe right now? | On a scale of 0 to 10, where 0 is normal and 10 is the hardest you can imagine, how short of breath are you feeling right now? | used |
| dc_retraction | red_flag | th | เวลาหายใจเข้า มีอกบุ๋มหรือซี่โครงบุ๋มไหมคะ | เวลาหายใจเข้า สังเกตเห็นว่าหน้าอกหรือซี่โครงบุ๋มลงไปบ้างไหมคะ | used |
| dc_retraction | red_flag | en | When you breathe in, do the spaces between your ribs or at the base of your neck pull inward? | When you breathe in, do you notice your ribs or the area at the base of your neck pulling inward? | used |
| dc_onset | slot | th | เริ่มไอหรือเหนื่อยตั้งแต่เมื่อไหร่คะ | คุณเริ่มมีอาการไอหรือรู้สึกเหนื่อยแบบนี้มานานกี่วันแล้วคะ | used |
| dc_onset | slot | en | When did the cough or breathlessness start? | When did you first notice the cough or trouble breathing? | used |
| dc_duration | slot | th | เป็นมากี่วันแล้วคะ เกิน 2 สัปดาห์หรือยัง | อาการที่เป็นอยู่นี้เริ่มเป็นมานานกี่วันแล้วคะ เกินสองสัปดาห์หรือยังเอ่ย | used |
| dc_duration | slot | en | How many days has it lasted? More than 2 weeks? | How many days have you been feeling this way, and has it been going on for more than two weeks? | used |
| dc_orthopnea | associated | th | นอนราบได้ไหมคะ แล้วขาบวมไหม | คุณนอนราบได้ปกติไหมคะ และมีอาการขาบวมหรือตัวบวมบ้างหรือเปล่าคะ | used |
| dc_orthopnea | associated | en | Can you lie flat at night, and are your legs swollen? | Are you able to lie flat when you sleep, or do you need to sit up to breathe? Also, have you noticed any swelling in your legs or body? | refused: question_count, too_long |
| dc_tb_signs | associated | th | ช่วงนี้มีไข้ตอนเย็น อ่อนเพลีย หรือน้ำหนักลดไหมคะ | ช่วงนี้คุณมีอาการไข้ต่ำ ๆ ตอนเย็น รู้สึกเพลีย หรือน้ำหนักลดลงบ้างไหมคะ | used |
| dc_tb_signs | associated | en | Any evening fevers, tiredness, or weight loss recently? | Have you been feeling tired, losing weight without trying, or getting a mild fever in the evenings? | used |
| ap_gi_bleed | red_flag | th | ในสัปดาห์ที่ผ่านมา อาเจียนเป็นเลือด ถ่ายเป็นเลือด หรือถ่ายดำไหมคะ | ในช่วงสัปดาห์ที่ผ่านมา คุณมีอาการอาเจียนเป็นเลือด ถ่ายเป็นเลือดสด หรือถ่ายอุจจาระเป็นสีดำบ้างไหมคะ | used |
| ap_gi_bleed | red_flag | en | Have you vomited blood, or had bloody or black stools in the past week? | Have you noticed any blood when you throw up, or have you seen any bright red or black, tarry stools in the last week? | used |
| ap_severity | scale | th | ให้คะแนนความปวด 0 ถึง 10 ตอนนี้ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกปวดมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ | used |
| ap_severity | scale | en | On a scale of 0 to 10, how severe is the pain? | How would you rate your pain on a scale from 0 to 10? | used |
| ap_pregnancy | red_flag | th | (ถ้าเกี่ยวข้อง) มีโอกาสตั้งครรภ์ ประจำเดือนขาด หรือมีเลือดออกทางช่องคลอดไหมคะ | ช่วงนี้มีอาการประจำเดือนขาด หรือมีเลือดออกผิดปกติทางช่องคลอดบ้างไหมคะ และมีโอกาสที่จะตั้งครรภ์ด้วยหรือเปล่าคะ | used |
| ap_pregnancy | red_flag | en | (If applicable) Could you be pregnant, is your period late, or do you have any vaginal bleeding? | Could you be pregnant, is your period late, or are you having any bleeding down there? | used |
| ap_location | slot | th | ปวดตรงส่วนไหนของท้องคะ ท้องบน ท้องน้อย ข้างซ้าย หรือข้างขวา | คุณรู้สึกปวดท้องบริเวณไหนมากที่สุดคะ | used |
| ap_location | slot | en | Where exactly is the pain — upper, lower, right, or left side? | Could you point to where you are feeling the pain? | used |
| ap_onset | slot | th | เริ่มปวดตั้งแต่เมื่อไหร่คะ | อาการปวดที่ว่านี้ เริ่มเป็นมาตั้งแต่เมื่อไหร่คะ | used |
| ap_onset | slot | en | When did the pain start? | When did you first start feeling this pain? | used |
| ap_character | slot | th | ปวดแบบบิด ๆ แสบร้อน หรือปวดตลอดเวลาคะ | อาการปวดท้องที่เป็นอยู่ มีลักษณะเป็นแบบบิดเกร็ง แสบร้อน หรือว่าปวดตลอดเวลาคะ | used |
| ap_character | slot | en | Is it a cramping, burning, or constant pain? | How would you describe the feeling of the pain? | used |
| ap_aggravating | slot | th | มีอะไรทำให้ปวดมากขึ้นหรือดีขึ้นไหมคะ เช่น หลังกินข้าว | มีกิจกรรมหรืออะไรที่ทำให้อาการปวดของคุณเปลี่ยนไปบ้างไหมคะ เช่น หลังทานอาหารหรือตอนขยับตัว | used |
| ap_aggravating | slot | en | Does anything make it better or worse, like eating? | Does anything you do, like eating or changing positions, make your symptoms feel better or worse? | used |
| ap_associated | associated | th | มีอาเจียน ถ่ายเหลว ไข้ หรือคลำเจอก้อนที่ท้องไหมคะ | ตอนนี้มีอาการคลื่นไส้อาเจียน ถ่ายเหลว มีไข้ หรือคลำเจอก้อนที่ท้องบ้างไหมคะ | used |
| ap_associated | associated | en | Any vomiting, diarrhea, fever, or a lump you can feel in your belly? | Have you been throwing up, having loose stools, feeling feverish, or noticed any lumps in your belly? | used |
| hd_befast | red_flag | th | มีปากเบี้ยว แขนขาอ่อนแรง พูดไม่ชัด ตามองไม่เห็นฉับพลัน หรือเดินเซไหมคะ | ตอนนี้มีอาการปากเบี้ยว พูดไม่ชัด แขนขาอ่อนแรง หรือเดินเซบ้างไหมคะ | used |
| hd_befast | red_flag | en | Any face drooping, arm or leg weakness, slurred speech, sudden vision loss, or loss of balance? | Are you having any sudden trouble with your face, arms, speech, vision, or balance? | refused: missing:limb_weakness |
| hd_thunderclap | red_flag | th | ปวดขึ้นมาฉับพลันรุนแรงที่สุดในชีวิตเลยไหมคะ | ตอนนี้คุณมีอาการปวดหัวรุนแรงมากแบบฉับพลันที่สุดในชีวิตเลยไหมคะ | used |
| hd_thunderclap | red_flag | en | Did the headache come on suddenly and feel like the worst headache of your life? | Did this headache come on very suddenly and feel like the worst one you have ever had? | refused: validator |
| hd_stiff_neck | red_flag | th | มีไข้ร่วมกับคอแข็ง ก้มคอลำบากไหมคะ | ตอนนี้มีอาการไข้ร่วมกับรู้สึกคอแข็งหรือก้มคอลำบากบ้างไหมคะ | used |
| hd_stiff_neck | red_flag | en | Do you have fever with a stiff neck? | Are you currently experiencing a fever along with a stiff neck? | used |
| hd_severity | scale | th | ให้คะแนนความปวด 0 ถึง 10 ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกปวดมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ | used |
| hd_severity | scale | en | On a scale of 0 to 10, how bad is the headache? | How would you rate the intensity of your headache on a scale of 0 to 10? | used |
| hd_onset | slot | th | เริ่มปวดเมื่อไหร่คะ | อาการปวดนี้เริ่มเป็นมาตั้งแต่เมื่อไหร่คะ | used |
| hd_onset | slot | en | When did it start? | About when did you first start feeling this way? | used |
| hd_duration | slot | th | ปวดมานานแค่ไหนแล้วคะ เป็นชั่วโมง เป็นวัน หรือนานกว่านั้น | อาการปวดที่เป็นอยู่นี้ เริ่มรู้สึกมานานแค่ไหนแล้วคะ | used |
| hd_duration | slot | en | How long has it lasted — hours, days, or longer? | How long have you been feeling this way? | used |
| hd_character | slot | th | ปวดตุบ ๆ ปวดบีบ หรือปวดตลอดเวลาคะ | อาการปวดของคุณมีลักษณะเป็นอย่างไรคะ | used |
| hd_character | slot | en | Is it throbbing, squeezing, or constant? | How would you describe the feeling of the pain? | used |
| hd_associated | associated | th | มีอาเจียนหรือบ้านหมุนร่วมด้วยไหมคะ | ตอนนี้มีอาการคลื่นไส้อาเจียน หรือรู้สึกเวียนหัวบ้านหมุนบ้างไหมคะ | used |
| hd_associated | associated | en | Any vomiting or spinning dizziness with it? | Are you feeling any nausea, throwing up, or a spinning sensation? | used |
| fv_danger | red_flag | th | มีซึมสับสน หายใจเหนื่อย หรือคอแข็งร่วมกับไข้ไหมคะ | ตอนนี้มีอาการซึมลง พูดจาสับสน หายใจเหนื่อย หรือก้มคอไม่ได้บ้างไหมคะ | used |
| fv_danger | red_flag | en | Any confusion, trouble breathing, or stiff neck with the fever? | Are you feeling confused, having any trouble breathing, or do you have a stiff neck along with your fever? | used |
| fv_chemo | red_flag | th | ตอนนี้กำลังได้รับยาเคมีบำบัดอยู่ไหมคะ | ตอนนี้คุณกำลังรับยาเคมีบำบัดอยู่ไหมคะ | used |
| fv_chemo | red_flag | en | Are you currently receiving chemotherapy? | Are you currently receiving chemotherapy? | same |
| fv_rash | red_flag | th | มีผื่นหรือตุ่มน้ำตามตัว โดยเฉพาะฝ่ามือ ฝ่าเท้า หรือรอบปากไหมคะ | ตอนนี้มีผื่นแดง ตุ่มน้ำใสขึ้นตามตัว หรือมีผื่นขึ้นที่ฝ่ามือฝ่าเท้าบ้างไหมคะ | used |
| fv_rash | red_flag | en | Do you have any rash or blisters, especially on palms, soles, or around the mouth? | Have you noticed any red rash or fluid-filled blisters on your body, or perhaps around your mouth, palms, or soles? | used |
| fv_onset | slot | th | เริ่มมีไข้ตั้งแต่เมื่อไหร่คะ | คุณเริ่มมีไข้ตั้งแต่เมื่อไหร่คะ | used |
| fv_onset | slot | en | When did the fever start? | When did you first notice your fever starting? | used |
| fv_duration | slot | th | มีไข้มากี่วันแล้วคะ | คุณมีอาการไข้มานานกี่วันแล้วคะ | used |
| fv_duration | slot | en | How many days have you had it? | About how many days have you been feeling this way? | used |
| fv_associated | associated | th | มีไอ เจ็บคอ น้ำมูก ถ่ายเหลว หรือปัสสาวะแสบขัดไหมคะ | ตอนนี้มีอาการไอ เจ็บคอ น้ำมูกไหล ถ่ายเหลว หรือปัสสาวะแสบขัดบ้างไหมคะ | used |
| fv_associated | associated | en | Any cough, sore throat, runny nose, diarrhea, or burning urination? | Are you having any coughing, a sore throat, a runny nose, loose stools, or burning when you pee? | used |
| ear_severe_pain_droop | red_flag | th | นอกจากปวดหู มีหน้าเบี้ยวข้างใดข้างหนึ่งไหมคะ | นอกจากอาการปวดหูแล้ว คุณมีอาการหน้าเบี้ยวหรือปากเบี้ยวบ้างไหมคะ | used |
| ear_severe_pain_droop | red_flag | en | Along with the ear pain, is your face drooping on one side? | Is your face drooping on one side or does your mouth look crooked? | used |
| ear_fb | red_flag | th | มีสิ่งแปลกปลอมเข้าไปติดในหูไหมคะ | ตอนนี้มีสิ่งของหรือแมลงเข้าไปติดอยู่ในหูบ้างไหมคะ | used |
| ear_fb | red_flag | en | Is there something stuck in your ear? | Is there something stuck in your ear, nose, or throat? | used |
| ear_severity | scale | th | ให้คะแนนความปวดหู 0 ถึง 10 ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกปวดหูมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ | used |
| ear_severity | scale | en | On a scale of 0 to 10, how bad is the ear pain? | On a scale of zero to ten, how would you rate your ear pain? | used |
| ear_onset | slot | th | เริ่มเป็นเมื่อไหร่คะ | อาการที่คุณเล่ามานี้ เริ่มมีอาการมานานแค่ไหนแล้วคะ | used |
| ear_onset | slot | en | When did it start? | About when did you first start feeling this way? | used |
| ear_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| ear_duration | slot | en | How long has it been going on? | How long have you been feeling this way? | used |
| ear_associated | associated | th | มีการได้ยินลดลง เสียงดังในหู น้ำไหลจากหู หรือบ้านหมุนเวลาเปลี่ยนท่าไหมคะ | ตอนนี้คุณมีอาการหูอื้อ ได้ยินไม่ชัด มีเสียงดังในหู มีน้ำไหลจากหู หรือรู้สึกบ้านหมุนเวลาเปลี่ยนท่าบ้างไหมคะ | used |
| ear_associated | associated | en | Any hearing loss, ringing in the ear, fluid from the ear, or spinning dizziness when you move your head? | Are you having any trouble hearing, ringing in your ears, fluid leaking out, or feeling dizzy when you turn your head? | used |
| nt_airway | red_flag | th | คอบวมโต กลืนลำบาก หรือหายใจลำบากไหมคะ | ตอนนี้มีอาการคอบวม กลืนลำบาก หรือหายใจลำบากบ้างไหมคะ | used |
| nt_airway | red_flag | en | Is your neck swollen, or is it hard to swallow or breathe? | Are you having any swelling in your neck, or are you finding it hard to swallow or breathe? | used |
| nt_epistaxis | red_flag | th | ถ้ามีเลือดกำเดา ตอนนี้หยุดแล้วหรือยังไหลอยู่คะ | ตอนนี้เลือดกำเดาหยุดไหลแล้วหรือยังคะ | used |
| nt_epistaxis | red_flag | en | If your nose is bleeding, has it stopped, or is it still bleeding now? | Is your nose still bleeding right now, or has it stopped? | used |
| nt_onset | slot | th | อาการเริ่มเมื่อไหร่คะ | อาการที่คุณเป็นอยู่เริ่มเกิดขึ้นตั้งแต่เมื่อไหร่คะ | used |
| nt_onset | slot | en | When did the symptoms start? | When did you first start feeling this way? | used |
| nt_duration | slot | th | เป็นมานานแค่ไหนคะ ถ้าเจ็บคอเกิน 1 เดือน หรือเสียงแหบเกิน 2 สัปดาห์ไหม | อาการเจ็บคอหรือเสียงแหบของคุณเป็นมานานแค่ไหนแล้วคะ | used |
| nt_duration | slot | en | How long has it lasted? For a sore throat — more than a month? For hoarseness — more than 2 weeks? | How long have you been dealing with this? | used |
| nt_associated | associated | th | มีก้อนที่คอหรือในปาก แผลในปากไม่หาย นอนกรน จมูกไม่ได้กลิ่น หรืออาการภูมิแพ้ไหมคะ | คุณมีอาการก้อนที่คอ แผลในปากไม่หาย กรน จมูกไม่ได้กลิ่น หรือมีอาการแพ้อากาศบ้างไหมคะ | used |
| nt_associated | associated | en | Any lump in the neck or mouth, mouth ulcer that won't heal, snoring, loss of smell, or allergy symptoms? | Are you currently dealing with any neck lumps, mouth sores that won't go away, snoring, loss of smell, or allergy symptoms like sneezing? | used |
| eye_chemical | red_flag | th | มีสารเคมีหรือพิษสัตว์กระเด็นเข้าตาไหมคะ | มีสารเคมีหรือพิษจากสัตว์กระเด็นเข้าตาบ้างไหมคะ | used |
| eye_chemical | red_flag | en | Did any chemical or venom splash into your eye? | Did you get any chemicals or animal venom splashed into your eye? | used |
| eye_trauma_q | red_flag | th | ตาโดนกระแทกหรือได้รับอุบัติเหตุไหมคะ แล้วมีเลือดออกไหม | ช่วงนี้ดวงตาได้รับอุบัติเหตุหรือโดนกระแทกมาบ้างไหมคะ และมีเลือดออกด้วยหรือเปล่า | used |
| eye_trauma_q | red_flag | en | Was there an injury to the eye, and is it bleeding? | Did you have an accident that hurt your eye, and is there any bleeding that won't stop? | used |
| eye_vision | red_flag | th | ตามัวหรือมองไม่เห็นขึ้นมาฉับพลันไหมคะ | ตอนนี้มีอาการตามัวหรือมองเห็นไม่ชัดขึ้นมาทันทีบ้างไหมคะ | used |
| eye_vision | red_flag | en | Has your vision suddenly become blurry or gone dark? | Has your vision suddenly become blurry or gone dark? | same |
| eye_onset | slot | th | อาการทางตาเริ่มเมื่อไหร่คะ | อาการผิดปกติที่ดวงตาของคุณเริ่มเกิดขึ้นตั้งแต่เมื่อไหร่คะ | used |
| eye_onset | slot | en | When did the eye problem start? | When did you first notice the trouble with your eye? | used |
| eye_associated | associated | th | ตาแดงมาก ปวดมาก หรือมีก้อนบวมที่ตาไหมคะ | ตอนนี้มีอาการตาแดงจัด ปวดตามาก หรือมีก้อนบวมที่บริเวณดวงตาบ้างไหมคะ | used |
| eye_associated | associated | en | Is the eye very red, very painful, or is there a swollen lump? | Are you experiencing severe eye pain, or do you have a red, swollen lump on your eyelid? | used |
| inj_mechanism | red_flag | th | บาดเจ็บจากอะไรคะ รถชน ตกจากที่สูง หรือถูกของมีคมแทง | ไม่ทราบว่าได้รับบาดเจ็บจากสาเหตุใดคะ เช่น รถชน ตกจากที่สูง หรือถูกของมีคมแทง | refused: not_a_question |
| inj_mechanism | red_flag | en | How did the injury happen — was it a vehicle accident, a fall from height, or a stab wound? | Could you tell me how the injury happened, such as a vehicle accident, a fall from a height, or a stab wound? | used |
| inj_bleeding | red_flag | th | มีเลือดออกมากจนหยุดไม่ได้ไหมคะ | ตอนนี้มีเลือดไหลออกมามากจนห้ามไม่อยู่เลยไหมคะ | used |
| inj_bleeding | red_flag | en | Is there heavy bleeding that won't stop? | Are you currently experiencing any heavy bleeding that you cannot get to stop? | used |
| inj_head | red_flag | th | ศีรษะกระแทกไหมคะ หลังจากนั้นมีซึมสับสนหรืออาเจียนไหม | คุณมีอาการศีรษะกระแทกบ้างไหมคะ แล้วหลังจากนั้นมีอาการซึมลง พูดจาสับสน หรืออาเจียนบ้างหรือเปล่าคะ | used |
| inj_head | red_flag | en | Did you hit your head? Any confusion or vomiting since? | Have you hit your head recently, or have you been feeling confused or throwing up? | used |
| inj_when | slot | th | บาดเจ็บเมื่อไหร่คะ ภายใน 24 ชั่วโมงที่ผ่านมาหรือเปล่า | ไม่ทราบว่าเหตุการณ์นี้เพิ่งเกิดขึ้นภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | used |
| inj_when | slot | en | When did the injury happen — within the last 24 hours? | About how long ago did this injury happen? | used |
| inj_fracture | associated | th | มีส่วนไหนผิดรูป ขยับไม่ได้ หรือลงน้ำหนักไม่ได้ไหมคะ | มีส่วนไหนของร่างกายที่ดูผิดรูป ขยับไม่ได้ หรือลงน้ำหนักไม่ได้บ้างไหมคะ | used |
| inj_fracture | associated | en | Does any bone look deformed, or can you not move or bear weight on the limb? | Does the area look misshapen, or are you unable to move or put weight on it? | refused: missing:fracture_suspected |
| inj_severity | scale | th | ให้คะแนนความปวด 0 ถึง 10 ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกปวดมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ | used |
| inj_severity | scale | en | On a scale of 0 to 10, how much pain are you in? | On a scale of 0 to 10, where 0 is no pain and 10 is the worst you can imagine, how much pain are you feeling right now? | used |
| inj_police | associated | th | เกี่ยวข้องกับการถูกทำร้าย หรือมีใบนำส่งจากตำรวจไหมคะ | วันนี้มีใบนำส่งจากตำรวจ หรือได้รับบาดเจ็บจากการถูกทำร้ายมาด้วยไหมคะ | used |
| inj_police | associated | en | Is this related to an assault or do you have a police referral document? | Were you physically attacked within the last day, or did the police send you here for an examination? | used |
| pg_crowning | red_flag | th | เจ็บครรภ์ถี่มาก (ทุก 2–3 นาที) หรือรู้สึกอยากเบ่ง เหมือนเด็กกำลังจะคลอดไหมคะ | ตอนนี้คุณรู้สึกเจ็บท้องถี่ทุก 2-3 นาที หรือรู้สึกเหมือนเด็กกำลังจะคลอดออกมาแล้วบ้างไหมคะ | used |
| pg_crowning | red_flag | en | Are contractions coming very frequently (every 2–3 minutes), or do you feel the baby coming? | Are you having strong contractions every few minutes, or does it feel like the baby is coming? | used |
| pg_ga | red_flag | th | อายุครรภ์กี่สัปดาห์แล้วคะ ถึง 24 สัปดาห์หรือยัง | ตอนนี้คุณแม่ตั้งครรภ์ได้กี่สัปดาห์แล้วคะ ถึง 24 สัปดาห์หรือยังเอ่ย | used |
| pg_ga | red_flag | en | How many weeks pregnant are you — 24 weeks or more? | Are you currently 24 weeks or more into your pregnancy? | used |
| pg_warning | red_flag | th | มีน้ำเดิน เลือดออกทางช่องคลอด หรือลูกดิ้นน้อยลงไหมคะ | ตอนนี้คุณมีอาการน้ำเดิน เลือดออกทางช่องคลอด หรือรู้สึกว่าลูกดิ้นน้อยลงบ้างไหมคะ | used |
| pg_warning | red_flag | en | Any water leaking, vaginal bleeding, or the baby moving less than usual? | Have you noticed your water breaking, any bleeding, or the baby moving less than usual? | used |
| pg_bp | associated | th | มีความดันสูง ปวดหัวมาก หรือแพ้ท้องรุนแรงจนกินไม่ได้ไหมคะ | คุณมีอาการความดันสูง ปวดหัวรุนแรง หรือแพ้ท้องหนักจนทานอะไรไม่ได้เลยบ้างไหมคะ | refused: not_yes_no |
| pg_bp | associated | en | Do you have high blood pressure, severe headaches, or vomiting so much you can't eat? | Do you have a history of high blood pressure, or are you vomiting so much that you cannot keep any food or drink down? | used |
| pg_onset | slot | th | อาการเริ่มเมื่อไหร่คะ | อาการที่คุณเป็นอยู่เริ่มเกิดขึ้นตั้งแต่เมื่อไหร่คะ | used |
| pg_onset | slot | en | When did these symptoms start? | When did you first start feeling this way? | used |
| mh_suicide | red_flag | th | มีความคิดอยากทำร้ายตัวเองหรืออยากตายไหมคะ | ช่วงนี้มีความคิดอยากทำร้ายตัวเอง หรืออยากตายบ้างไหมคะ | used |
| mh_suicide | red_flag | en | Have you had thoughts of hurting yourself or ending your life? | Are you having any thoughts about hurting yourself or ending your life? | used |
| mh_onset | slot | th | เริ่มรู้สึกแบบนี้ตั้งแต่เมื่อไหร่คะ | คุณเริ่มมีอาการนี้มานานแค่ไหนแล้วคะ | used |
| mh_onset | slot | en | When did you start feeling this way? | About how long have you been feeling this way? | used |
| mh_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| mh_duration | slot | en | How long has it been going on? | About how long have you been feeling this way? | used |
| mh_psychosis | associated | th | บางครั้งได้ยินเสียงคนพูดหรือเห็นสิ่งที่คนอื่นไม่เห็น หรือรู้สึกหวาดระแวงว่าจะมีคนมาทำร้ายไหมคะ | คุณเคยได้ยินเสียงคนพูด หรือเห็นภาพที่คนอื่นไม่เห็นบ้างไหมคะ | refused: missing:hallucination_paranoia |
| mh_psychosis | associated | en | Do you sometimes hear voices or see things others don't, or feel that someone is out to harm you? | Do you ever hear voices, see things others don't, or feel like someone is trying to hurt you? | used |
| msk_injury | red_flag | th | มีอุบัติเหตุหรือการบาดเจ็บมาก่อนไหมคะ มีส่วนไหนผิดรูปเหมือนกระดูกหักหรือข้อหลุดไหม | คุณได้รับบาดเจ็บตรงไหนมาบ้างคะ และมีส่วนไหนที่ดูผิดรูปหรือผิดตำแหน่งไปจากเดิมไหมคะ | refused: missing:fracture_suspected |
| msk_injury | red_flag | en | Was there a recent injury, and does anything look broken or dislocated? | Did you have an injury in the last day that makes you think a bone is broken or a joint is out of place? | used |
| msk_radiating | associated | th | อาการปวดหลังร้าวลงขาไหมคะ | คุณมีอาการปวดหลังที่ร้าวลงไปที่ขาบ้างไหมคะ | used |
| msk_radiating | associated | en | Does the back pain shoot down your leg? | Does your back pain travel down into your leg? | used |
| msk_onset | slot | th | เริ่มปวดเมื่อไหร่คะ | อาการปวดที่ว่านี้ เริ่มเป็นมาตั้งแต่เมื่อไหร่คะ | used |
| msk_onset | slot | en | When did the pain start? | When did you first start feeling this pain? | used |
| msk_duration | slot | th | ปวดมานานแค่ไหนแล้วคะ | อาการปวดที่เป็นอยู่นี้ เริ่มรู้สึกมานานแค่ไหนแล้วคะ | used |
| msk_duration | slot | en | How long has it lasted? | About how long have you been feeling this way? | used |
| msk_severity | scale | th | ให้คะแนนความปวด 0 ถึง 10 ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกปวดมากน้อยแค่ไหนคะ โดยให้คะแนนจาก 0 ถึง 10 ค่ะ | used |
| msk_severity | scale | en | On a scale of 0 to 10, how bad is the pain? | On a scale of zero to ten, how would you rate your pain right now? | used |
| msk_aggravating | slot | th | อะไรทำให้ปวดมากขึ้นคะ เช่น ขยับ เดิน หรือนั่งพัก | อาการปวดของคุณเป็นมากขึ้นตอนไหนคะ เช่น เวลาขยับตัว เดิน หรือตอนนั่งพักเฉย ๆ | used |
| msk_aggravating | slot | en | What makes it worse — moving, walking, or resting? | Does moving around, walking, or resting make your discomfort feel any different? | used |
| ur_fever_flank | red_flag | th | มีไข้หรืออาเจียนร่วมกับอาการปัสสาวะไหมคะ | ตอนนี้มีอาการไข้ ตัวร้อน หรืออาเจียนร่วมด้วยบ้างไหมคะ | used |
| ur_fever_flank | red_flag | en | Do you have fever or vomiting along with the urinary symptoms? | Are you also feeling feverish or dealing with any throwing up? | used |
| ur_onset | slot | th | เริ่มเป็นเมื่อไหร่คะ | อาการที่คุณเล่ามานี้ เริ่มรู้สึกผิดปกติมานานเท่าไหร่แล้วคะ | used |
| ur_onset | slot | en | When did it start? | About when did you first start feeling this way? | used |
| ur_duration | slot | th | เป็นมากี่วันแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานกี่วันแล้วคะ | used |
| ur_duration | slot | en | How many days has it been? | How many days have you been feeling this way? | used |
| ur_character | slot | th | มีแสบขัด ปัสสาวะมีเลือดปน หรือปัสสาวะไม่ออกไหมคะ | เวลาปัสสาวะมีอาการแสบขัด มีเลือดปน หรือปัสสาวะไม่ออกบ้างไหมคะ | used |
| ur_character | slot | en | Is there burning, blood in the urine, or trouble passing urine? | Are you having any pain, blood, or trouble when you go to the bathroom? | used |
| ws_bleeding | red_flag | th | แผลมีเลือดออกมากจนห้ามเลือดไม่หยุดไหมคะ | ตอนนี้แผลมีเลือดไหลออกมามากจนห้ามไม่อยู่เลยใช่ไหมคะ | used |
| ws_bleeding | red_flag | en | Is the wound bleeding heavily and won't stop? | Are you currently bleeding a lot and unable to get it to stop? | used |
| ws_infection | red_flag | th | รอบแผลแดงลาม ร้อน มีหนอง หรือมีไข้ร่วมด้วยไหมคะ | บริเวณรอบแผลมีอาการบวมแดง ร้อน หรือมีหนองไหลออกมาบ้างไหมคะ และมีอาการไข้ร่วมด้วยหรือเปล่า | used |
| ws_infection | red_flag | en | Is the skin around the wound spreading red, hot, or draining pus — or do you have a fever? | Is the skin around your wound red, hot, or leaking fluid, or have you felt feverish? | used |
| ws_onset | slot | th | แผลนี้เกิดขึ้นเมื่อไหร่คะ | แผลที่พบนี้เกิดขึ้นมานานหรือยังคะ | used |
| ws_onset | slot | en | When did the wound happen? | About how long ago did you get this injury? | used |
| ws_duration | slot | th | เป็นแผลมานานแค่ไหนแล้วคะ | แผลที่เป็นอยู่นี้เริ่มมีอาการมานานกี่วันหรือกี่สัปดาห์แล้วคะ | used |
| ws_duration | slot | en | How long has the wound been there? | How long has that wound been there? | used |
| ws_character | slot | th | แผลหรือปัญหาผิวหนังเป็นแบบไหนคะ | ตอนนี้แผลหรือผื่นที่ผิวหนังมีลักษณะเป็นอย่างไรบ้างคะ | used |
| ws_character | slot | en | What kind of wound or skin problem is it? | Could you tell me a little more about the wound or skin issue you are having? | used |
| ws_severity | scale | th | ให้คะแนนความเจ็บ 0 ถึง 10 ตอนนี้ประมาณเท่าไหร่คะ | ตอนนี้คุณรู้สึกเจ็บปวดมากน้อยแค่ไหนคะ โดยให้คะแนนตั้งแต่ 0 ถึง 10 ค่ะ | used |
| ws_severity | scale | en | On a scale of 0 to 10, how much does it hurt right now? | On a scale of 0 to 10, where 0 is no pain and 10 is the worst you can imagine, how much does it hurt right now? | used |
| ws_associated | associated | th | เป็นแผลเรื้อรัง แผลเป็นมีปัญหา ถูกสัตว์หรือแมลงกัด หรือแผลไฟไหม้น้ำร้อนลวกไหมคะ | ตอนนี้คุณมีแผลเรื้อรัง แผลเป็นที่มีปัญหา แผลไฟไหม้น้ำร้อนลวก หรือแผลจากสัตว์กัดบ้างไหมคะ | used |
| ws_associated | associated | en | Is it a long-standing wound, a problem scar, an animal or insect bite, or a burn? | Are you here because of a long-standing wound, a problem scar, a recent bite or sting, or a burn? | used |
| gyn_heavy_bleeding | red_flag | th | เลือดออกทางช่องคลอดมากจนผ้าอนามัยชุ่มทุก 1 ชั่วโมงไหมคะ | ตอนนี้มีเลือดออกมากจนต้องเปลี่ยนผ้าอนามัยทุกชั่วโมงเลยไหมคะ | used |
| gyn_heavy_bleeding | red_flag | en | Is the vaginal bleeding very heavy — soaking a pad every hour? | Are you soaking through a pad every hour because of the bleeding? | used |
| gyn_pregnancy | red_flag | th | มีโอกาสตั้งครรภ์ หรือประจำเดือนขาดไหมคะ | ตอนนี้คุณกำลังตั้งครรภ์ หรือมีอาการประจำเดือนขาดไปบ้างไหมคะ | used |
| gyn_pregnancy | red_flag | en | Could you be pregnant, or is your period late? | Could you be pregnant, or is your period late? | same |
| gyn_pelvic_pain | red_flag | th | ปวดท้องน้อยหรืออุ้งเชิงกรานรุนแรงไหมคะ | ตอนนี้รู้สึกปวดท้องน้อยหรือปวดบริเวณอุ้งเชิงกรานบ้างไหมคะ | used |
| gyn_pelvic_pain | red_flag | en | Do you have severe pain in your lower abdomen or pelvis? | Are you feeling any sharp or intense pain in your lower belly or pelvic area? | used |
| gyn_onset | slot | th | อาการเริ่มเป็นเมื่อไหร่คะ | อาการที่คุณเล่ามานี้ เริ่มมีอาการมาตั้งแต่เมื่อไหร่คะ | used |
| gyn_onset | slot | en | When did the symptoms start? | About when did you first start feeling this way? | used |
| gyn_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| gyn_duration | slot | en | How long has it been going on? | How long have you been feeling this way? | used |
| gyn_character | slot | th | อาการหลักคืออะไรคะ เลือดออก ตกขาว คัน หรือประจำเดือนมาไม่ปกติ | วันนี้มีอาการทางนรีเวชด้านไหนที่ทำให้กังวลใจคะ | used |
| gyn_character | slot | en | What is the main problem — bleeding, discharge, itching, or irregular periods? | What is the main concern you are having today? | used |
| gyn_associated | associated | th | มีเลือดออกหรือมีไข้ร่วมด้วยไหมคะ | ตอนนี้มีอาการไข้ขึ้นหรือมีเลือดออกผิดปกติบ้างไหมคะ | used |
| gyn_associated | associated | en | Do you have any bleeding or fever as well? | Are you experiencing any bleeding down there or a high temperature? | used |
| br_infection | red_flag | th | เต้านมแดง ร้อน หรือบวม หรือมีไข้ร่วมด้วยไหมคะ | ตอนนี้มีอาการเต้านมบวมแดง ร้อน หรือมีไข้ตัวร้อนร่วมด้วยบ้างไหมคะ | used |
| br_infection | red_flag | en | Is the breast red, hot, or swollen — or do you have a fever? | Are you noticing any redness, warmth, or swelling in your breast, or have you been feeling feverish? | used |
| br_onset | slot | th | สังเกตเห็นอาการครั้งแรกเมื่อไหร่คะ | คุณเริ่มรู้สึกไม่สบายแบบนี้มาตั้งแต่เมื่อไหร่คะ | used |
| br_onset | slot | en | When did you first notice it? | When did you first start feeling this way? | used |
| br_duration | slot | th | สังเกตเห็นก้อนหรืออาการนี้มานานแค่ไหนแล้วคะ | คุณเริ่มสังเกตเห็นก้อนหรืออาการนี้มานานแค่ไหนแล้วคะ | used |
| br_duration | slot | en | How long have you noticed the lump or symptom? | How long has this been going on? | used |
| br_character | slot | th | อาการหลักคืออะไรคะ มีก้อน เจ็บ หรือมีน้ำไหลจากหัวนม | ตอนนี้มีอาการผิดปกติอย่างไรบ้างคะ เช่น มีก้อนเนื้อ มีอาการเจ็บ หรือมีน้ำไหลออกมาจากหัวนมคะ | used |
| br_character | slot | en | What is the main concern — a lump, pain, or discharge from the nipple? | What is the main concern you are having with your breast? | used |
| br_associated | associated | th | มีก้อน เจ็บเต้านม หรือน้ำไหลจากหัวนมไหมคะ | ตอนนี้คุณมีอาการเจ็บเต้านม หรือมีน้ำไหลออกจากหัวนมบ้างไหมคะ | used |
| br_associated | associated | en | Do you have a lump, pain, or discharge from the nipple? | Are you currently experiencing a lump in your breast, any breast pain, or discharge from the nipple? | used |
| palp_syncope | red_flag | th | ช่วง 24 ชั่วโมงที่ผ่านมา มีวูบหมดสติหรือเกือบหมดสติไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณมีอาการวูบหมดสติไปบ้างไหมคะ | used |
| palp_syncope | red_flag | en | Have you fainted or nearly fainted in the past 24 hours? | Have you fainted or felt like you were going to pass out in the last day, without any injury causing it? | used |
| palp_chest_pain | red_flag | th | มีเจ็บหรือแน่นหน้าอกร่วมกับใจสั่นไหมคะ | คุณมีอาการเจ็บแน่นหน้าอก หรือจุกแน่นใต้ลิ้นปี่บ้างไหมคะ | used |
| palp_chest_pain | red_flag | en | Do you have chest pain or tightness along with the palpitations? | Are you feeling any chest pain or tightness along with those heart flutters? | used |
| palp_cardiac_history | red_flag | th | มีโรคหัวใจหรือหัวใจเต้นผิดจังหวะอยู่เดิมไหมคะ | คุณเคยมีประวัติเป็นโรคหัวใจ หรือมีปัญหาเส้นเลือดหัวใจตีบมาก่อนไหมคะ | used |
| palp_cardiac_history | red_flag | en | Do you have known heart disease or an existing heart rhythm problem? | Have you ever been told by a doctor that you have heart disease or a heart rhythm problem? | refused: validator |
| palp_onset | slot | th | อาการใจสั่นเริ่มเป็นเมื่อไหร่คะ | อาการใจสั่นที่รู้สึกอยู่นี้ เริ่มเป็นมานานแค่ไหนแล้วคะ | used |
| palp_onset | slot | en | When did the palpitations start? | About how long ago did you first notice your heart racing? | used |
| palp_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| palp_duration | slot | en | How long has this been happening? | About how long have you been feeling this way? | used |
| palp_character | slot | th | ลักษณะเป็นแบบไหนคะ ใจเต้นเร็ว เต้นแรง หรือเต้นสะดุด | อาการใจสั่นที่คุณรู้สึก มีลักษณะเป็นอย่างไรบ้างคะ | used |
| palp_character | slot | en | What does it feel like — racing, pounding, or skipping beats? | How would you describe the feeling in your chest—is it racing, pounding, or skipping beats? | used |
| palp_associated | associated | th | มีชีพจรเต้นไม่สม่ำเสมอ เหนื่อยง่าย ความดันสูง หรือเบาหวานร่วมด้วยไหมคะ | คุณมีอาการหัวใจเต้นไม่เป็นจังหวะ หายใจเหนื่อย หรือมีโรคประจำตัวอย่างความดันสูงหรือเบาหวานบ้างไหมคะ | used |
| palp_associated | associated | en | Do you also notice an irregular pulse, breathlessness, high blood pressure, or diabetes? | Do you ever feel like your heart is skipping beats or have trouble catching your breath? Also, do you have a history of high blood pressure or diabetes? | refused: question_count |
| lv_ischemia | red_flag | th | แขนหรือขาปวดรุนแรงเฉียบพลัน ร่วมกับซีดและเย็นไหมคะ | ตอนนี้มีอาการปวดแขนหรือขาอย่างรุนแรงกะทันหัน ร่วมกับผิวหนังดูซีดหรือเย็นลงบ้างไหมคะ | used |
| lv_ischemia | red_flag | en | Did an arm or leg suddenly become very painful, pale, and cold? | Have you noticed any of your arms or legs suddenly becoming very painful, pale, or cold? | used |
| lv_dvt | red_flag | th | ขาบวมและปวดเพียงข้างเดียวไหมคะ | ตอนนี้มีอาการขาบวมหรือปวดแค่ข้างเดียวบ้างไหมคะ | used |
| lv_dvt | red_flag | en | Is one leg swollen and painful, but not the other? | Is one of your legs swollen and painful while the other feels normal? | used |
| lv_onset | slot | th | อาการเริ่มเป็นเมื่อไหร่คะ | อาการที่คุณเล่ามานี้ เริ่มมีอาการมาตั้งแต่เมื่อไหร่คะ | used |
| lv_onset | slot | en | When did it start? | About when did you first start feeling this way? | used |
| lv_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| lv_duration | slot | en | How long has it been going on? | About how long have you been feeling this way? | used |
| lv_character | slot | th | อาการหลักคืออะไรคะ บวม เส้นเลือดขอด ปวด หรือปัญหาเส้นฟอกไต | วันนี้มีอาการอย่างไรบ้างคะ | used |
| lv_character | slot | en | What is the main problem — swelling, varicose veins, pain, or a dialysis access issue? | What is the main concern you are having with your leg today? | used |
| lv_associated | associated | th | มีเส้นเลือดขอด อาการบวม หรือต้องดูแลเส้นฟอกไตไหมคะ | คุณมีอาการเส้นเลือดขอด อาการบวม หรือต้องดูแลเส้นสำหรับฟอกไตอยู่บ้างไหมคะ | refused: missing:dialysis_access_needed |
| lv_associated | associated | en | Do you have varicose veins, swelling, or do you need dialysis access care? | Are you currently dealing with varicose veins, swollen legs, or do you need help setting up dialysis access? | used |
| fo_safety | red_flag | th | ตอนนี้คุณปลอดภัยไหมคะ หรือผู้ที่ทำร้ายยังอยู่ใกล้ ๆ | ตอนนี้คุณอยู่ในที่ที่ปลอดภัยหรือยังคะ หรือว่าคนที่ทำร้ายคุณยังอยู่ใกล้ ๆ หรือเปล่า | used |
| fo_safety | red_flag | en | Are you safe right now, or is the person who hurt you still nearby? | Are you in a safe place right now, or is the person who hurt you still nearby? | used |
| fo_assault | red_flag | th | ถูกทำร้ายร่างกายภายใน 24 ชั่วโมง หรือถูกล่วงละเมิดทางเพศภายใน 3 วันที่ผ่านมาไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณถูกทำร้ายร่างกาย หรือถูกล่วงละเมิดทางเพศภายใน 3 วันนี้หรือไม่คะ | used |
| fo_assault | red_flag | en | Were you physically assaulted within the last 24 hours, or sexually assaulted within the last 3 days? | Have you been physically attacked in the last day, or sexually assaulted in the last three days? | used |
| fo_unconscious | red_flag | th | มีศีรษะถูกกระแทกหรือหมดสติช่วงใดช่วงหนึ่งไหมคะ | ไม่ทราบว่าคุณมีอาการศีรษะกระแทกหรือหมดสติไปบ้างไหมคะ | used |
| fo_unconscious | red_flag | en | Did you hit your head or lose consciousness at any point? | Have you hit your head or fainted at all in the last day? | used |
| fo_onset | slot | th | เหตุการณ์เกิดขึ้นเมื่อไหร่คะ | อาการที่ว่านี้เริ่มเป็นมานานแค่ไหนแล้วคะ | used |
| fo_onset | slot | en | When did it happen? | About how long ago did this start? | used |
| fo_injuries | associated | th | มีเลือดออก สงสัยกระดูกหัก หรือบาดเจ็บส่วนอื่นไหมคะ | ตอนนี้มีแผลเลือดออก หรือรู้สึกว่ามีกระดูกหักหรือข้อเคลื่อนตรงไหนบ้างไหมคะ | refused: not_yes_no |
| fo_injuries | associated | en | Do you have bleeding, a possible broken bone, or other injuries? | Are you dealing with heavy bleeding that won't stop, a bone that might be broken, or an injury from the last 24 hours? | used |
| fo_police | associated | th | ได้แจ้งความกับตำรวจแล้ว หรือต้องการแจ้งความไหมคะ | คุณได้แจ้งความกับเจ้าหน้าที่ตำรวจไว้แล้ว หรือต้องการให้ทางเราช่วยประสานงานแจ้งความให้ไหมคะ | used |
| fo_police | associated | en | Has this been reported to the police, or would you like it to be? | Do you have a police report or a referral document from the police for this visit? | used |
| gi_blood | red_flag | th | อาเจียนเป็นเลือด ถ่ายเป็นเลือด หรือถ่ายดำไหมคะ | คุณมีอาการอาเจียนเป็นเลือด ถ่ายเป็นเลือดสด หรือถ่ายอุจจาระออกมาเป็นสีดำบ้างไหมคะ | used |
| gi_blood | red_flag | en | Have you vomited blood, or had red or black stools? | Have you noticed any blood when you throw up, or have you seen any bright red or black, tarry stools? | used |
| gi_dehydration | red_flag | th | ดื่มน้ำแล้วอาเจียนออกหมด ปัสสาวะน้อยลงมาก หรือลุกแล้วหน้ามืดไหมคะ | ตอนนี้คุณมีอาการดื่มน้ำแล้วอาเจียนออกหมด ลุกขึ้นแล้วรู้สึกหน้ามืด หรือกินน้ำไม่ได้บ้างไหมคะ | used |
| gi_dehydration | red_flag | en | Can you keep fluids down — or are you urinating very little or feeling faint when standing? | Are you able to keep liquids down, or have you noticed you are urinating very little or feeling faint when you stand up? | used |
| gi_severe_pain | red_flag | th | ปวดท้องรุนแรงมากจนทนไม่ไหวไหมคะ | ตอนนี้คุณรู้สึกปวดท้องรุนแรงมากจนทนไม่ไหว หรือปวดที่สุดในชีวิตเลยไหมคะ | used |
| gi_severe_pain | red_flag | en | Do you have very severe abdominal pain that you cannot bear? | Are you currently experiencing the worst, unbearable pain in your stomach? | used |
| gi_onset | slot | th | เริ่มท้องเสียหรืออาเจียนเมื่อไหร่คะ | เริ่มมีอาการถ่ายเหลวหรืออาเจียนมาตั้งแต่เมื่อไหร่คะ | used |
| gi_onset | slot | en | When did the diarrhea or vomiting start? | When did you first start feeling sick with the vomiting or diarrhea? | used |
| gi_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| gi_duration | slot | en | How long has it been going on? | About how long have you been feeling this way? | used |
| gi_character | slot | th | วันนี้ถ่ายเหลวหรืออาเจียนไปกี่ครั้งแล้วคะ | วันนี้คุณมีอาการถ่ายเหลวหรืออาเจียนรวมกันแล้วประมาณกี่ครั้งคะ | used |
| gi_character | slot | en | How many times today have you had diarrhea or vomited? | About how many times have you been sick or had loose stools today? | used |
| gi_associated | associated | th | มีไข้หรือปวดท้องร่วมด้วยไหมคะ | ตอนนี้มีอาการไข้ขึ้นหรือรู้สึกปวดท้องบ้างไหมคะ | used |
| gi_associated | associated | en | Do you also have fever or stomach pain? | Are you feeling feverish or having any stomach pain right now? | used |
| sr_anaphylaxis | red_flag | th | มีปากหรือหน้าบวม หรือหายใจลำบากไหมคะ | ตอนนี้มีอาการหน้าบวม ปากบวม หรือรู้สึกหายใจเหนื่อยบ้างไหมคะ | used |
| sr_anaphylaxis | red_flag | en | Are your lips or face swelling, or is it hard to breathe? | Are you having any swelling around your lips, mouth, or face, or are you finding it hard to catch your breath? | used |
| sr_spreading | red_flag | th | ผื่นลามเร็วภายในไม่กี่ชั่วโมง ร่วมกับมีไข้ไหมคะ | ตอนนี้มีผื่นขึ้นลามเร็วทั่วตัวภายในไม่กี่ชั่วโมง หรือมีอาการไข้ตัวร้อนร่วมด้วยไหมคะ | used |
| sr_spreading | red_flag | en | Is the rash spreading quickly — within hours — together with a fever? | Is your rash spreading quickly, like within a few hours, and do you also have a fever? | used |
| sr_onset | slot | th | ผื่นเริ่มขึ้นเมื่อไหร่คะ | ผื่นที่เห็นนี้เริ่มขึ้นมาตั้งแต่เมื่อไหร่คะ | used |
| sr_onset | slot | en | When did the rash start? | When did you first notice the rash appearing? | used |
| sr_duration | slot | th | เป็นมานานแค่ไหนแล้วคะ | อาการที่เป็นอยู่นี้ เริ่มมีมานานแค่ไหนแล้วคะ | used |
| sr_duration | slot | en | How long has it been there? | About how long have you noticed this? | used |
| sr_character | slot | th | ผื่นมีลักษณะแบบไหนคะ ตุ่มคัน ลมพิษ หรือตุ่มน้ำ | ผื่นที่ขึ้นตามตัวมีลักษณะเป็นอย่างไรบ้างคะ | used |
| sr_character | slot | en | What does the rash look like — itchy bumps, hives, or blisters? | Could you describe what the rash looks like? | used |
| sr_associated | associated | th | มีอาการคัน มีตุ่มน้ำ หรือมีประวัติแพ้อะไรไหมคะ | ตอนนี้มีผื่นแดง ตุ่มน้ำใสขึ้นตามตัว หรือมีประวัติแพ้อาหารและสิ่งของอะไรบ้างไหมคะ | used |
| sr_associated | associated | en | Is it itchy, are there blisters, or do you have known allergies? | Are you dealing with an itchy rash, any blisters, or do you have any known allergies to food or medicine? | used |
| cf_symptoms | red_flag | th | ตอนนี้มีเจ็บหน้าอก เหนื่อยง่าย หรืออาการน้ำตาลต่ำ เช่น มือสั่น เหงื่อแตก ไหมคะ | ตอนนี้มีอาการเจ็บแน่นหน้าอก หายใจเหนื่อย หรือรู้สึกเหมือนน้ำตาลตก เช่น เหงื่อแตกบ้างไหมคะ | used |
| cf_symptoms | red_flag | en | Right now, do you have chest pain, breathlessness, or low-blood-sugar symptoms like shakiness and cold sweats? | Are you feeling any chest tightness, shortness of breath, or perhaps shaky and sweaty right now? | used |
| cf_condition | slot | th | วันนี้มาติดตามโรคอะไรคะ | วันนี้คุณตั้งใจมาพบคุณหมอเพื่อติดตามอาการเกี่ยวกับโรคอะไรคะ | used |
| cf_condition | slot | en | Which condition are you following up today? | What brings you in to see us today? | used |
| cf_meds | associated | th | ยาประจำหมดแล้วหรือใกล้หมดไหมคะ | ไม่ทราบว่าตอนนี้ยาประจำตัวของคุณหมดแล้ว หรือว่าใกล้จะหมดคะ | refused: not_yes_no |
| cf_meds | associated | en | Have your regular medications run out, or are they about to? | Have you run out of your regular medication, or are you about to? | used |
| cf_duration | slot | th | ครั้งล่าสุดที่มาตรวจนานแค่ไหนแล้วคะ | คุณเคยมาตรวจที่โรงพยาบาลของเราครั้งล่าสุดเมื่อนานมาแล้วหรือยังคะ | used |
| cf_duration | slot | en | How long has it been since your last visit? | About how long has it been since you were last seen here? | used |
| cf_history | associated | th | มีโรคประจำตัวความดันสูง เบาหวาน หรือโรคหัวใจไหมคะ | คุณมีโรคประจำตัวอย่างความดันสูง เบาหวาน หรือโรคหัวใจบ้างไหมคะ | used |
| cf_history | associated | en | Do you have high blood pressure, diabetes, or heart disease on record? | Do you have a history of high blood pressure, diabetes, or heart problems? | used |
| ad_service | slot | th | วันนี้ต้องการเอกสารหรือบริการอะไรคะ | วันนี้คุณต้องการติดต่อเรื่องอะไรหรือรับบริการด้านไหนคะ | used |
| ad_service | slot | en | What document or service do you need today? | What brings you to our desk today? | used |
| confirm_abdominal_pain | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ปวดท้องอยู่ไหมคะ | ตอนนี้คุณมีอาการปวดท้อง หรือจุกเสียดท้องอยู่บ้างไหมคะ | used |
| confirm_abdominal_pain | red_flag | en | Just to be sure — do you have abdominal pain right now? | Are you feeling any pain in your stomach or belly right now? | used |
| confirm_abnormal_breath_sounds | red_flag | th | ขอถามให้ชัดนะคะ เวลาหายใจได้ยินเสียงหวีดหรือครืดคราดชัด ๆ ไหมคะ | เวลาหายใจเข้าหรือออก คุณได้ยินเสียงหวีดหรือเสียงครืดคราดบ้างไหมคะ | used |
| confirm_abnormal_breath_sounds | red_flag | en | Just to be sure — can you hear a wheeze or a harsh sound when you breathe, without a stethoscope? | Can you hear any wheezing or harsh, noisy sounds when you breathe? | used |
| confirm_agitation_violent | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้มีอาการคลุ้มคลั่งหรืออาละวาดอยู่ไหมคะ | ตอนนี้มีอาการคลุ้มคลั่งหรืออาละวาดบ้างไหมคะ | used |
| confirm_agitation_violent | red_flag | en | Just to be sure — is the person severely agitated or violent right now? | Is the person acting very upset, violent, or out of control right now? | used |
| confirm_airway_obstruction | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้มีอะไรติดคอหรือสำลักจนหายใจไม่ออกไหมคะ | ตอนนี้คุณรู้สึกเหมือนมีอะไรติดคอหรือสำลักจนหายใจไม่ออกบ้างไหมคะ | used |
| confirm_airway_obstruction | red_flag | en | Just to be sure — is something blocking the airway, or are you choking right now? | Are you currently choking or is something stuck in your throat blocking your breathing? | used |
| confirm_amniotic_fluid_leak | red_flag | th | ขอถามให้ชัดนะคะ น้ำเดินหรือมีน้ำคร่ำไหลออกมาใช่ไหมคะ | ตอนนี้มีน้ำใส ๆ ไหลออกมาทางช่องคลอดบ้างไหมคะ | refused: missing:amniotic_fluid_leak |
| confirm_amniotic_fluid_leak | red_flag | en | Just to be sure — has your water broken, or is amniotic fluid leaking? | I need to check one more thing. Has your water broken, or do you feel like you are leaking amniotic fluid? | used |
| confirm_animal_insect_bite_24h | red_flag | th | ขอถามให้ชัดนะคะ ถูกแมลงสัตว์กัดต่อยภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณถูกแมลงสัตว์กัดต่อยหรือถูกหมากัดบ้างไหมคะ | used |
| confirm_animal_insect_bite_24h | red_flag | en | Just to be sure — were you bitten or stung by an animal or insect within the last 24 hours? | Have you been bitten or stung by an animal or insect, like a dog, in the last 24 hours? | used |
| confirm_apnea | red_flag | th | ขอถามให้ชัดนะคะ มีช่วงที่หยุดหายใจไปเลยใช่ไหมคะ | มีช่วงที่สังเกตเห็นว่าเขามีอาการหยุดหายใจไปเป็นพัก ๆ บ้างไหมคะ | used |
| confirm_apnea | red_flag | en | Just to be sure — has the breathing stopped at any point? | Has there been any moment where the breathing has stopped? | used |
| confirm_assault_24h | red_flag | th | ขอถามให้ชัดนะคะ ถูกทำร้ายร่างกายภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณถูกทำร้ายร่างกายมาใช่ไหมคะ | used |
| confirm_assault_24h | red_flag | en | Just to be sure — were you physically assaulted within the last 24 hours? | Have you been physically attacked within the last 24 hours? | used |
| confirm_balance_loss | red_flag | th | ขอถามให้ชัดนะคะ เสียการทรงตัวหรือเวียนศีรษะฉับพลันจนเดินเซใช่ไหมคะ | คุณมีอาการเวียนศีรษะรุนแรงฉับพลัน หรือรู้สึกทรงตัวไม่ได้จนเดินเซบ้างไหมคะ | used |
| confirm_balance_loss | red_flag | en | Just to be sure — did you have a sudden loss of balance, or feel so dizzy you can't walk straight? | Have you had a sudden loss of balance, or are you feeling so dizzy that you are staggering or unable to walk straight? | used |
| confirm_bloody_stool | red_flag | th | ขอถามให้ชัดนะคะ ช่วงนี้ถ่ายเป็นเลือดสดใช่ไหมคะ | ช่วงนี้คุณมีอาการถ่ายเป็นเลือดสดบ้างไหมคะ | used |
| confirm_bloody_stool | red_flag | en | Just to be sure — have you passed fresh blood in your stool recently? | Have you noticed any fresh blood in your stool lately? | used |
| confirm_blue_lips | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ริมฝีปากเขียวหรือตัวเขียวอยู่ไหมคะ | ตอนนี้สังเกตเห็นว่าริมฝีปากหรือตัวมีสีเขียวคล้ำบ้างไหมคะ | used |
| confirm_blue_lips | red_flag | en | Just to be sure — are the lips or skin looking blue right now? | Are your lips or skin looking blue right now? | used |
| confirm_breast_infection_signs | red_flag | th | ขอถามให้ชัดนะคะ เต้านมแดง ร้อน หรือบวมอยู่ไหมคะ | ตอนนี้เต้านมของคุณมีอาการแดง ร้อน หรือบวมบ้างไหมคะ | used |
| confirm_breast_infection_signs | red_flag | en | Just to be sure — is the breast red, warm, or swollen? | Is there any redness, warmth, or swelling in your breast? | used |
| confirm_burn_scald_24h | red_flag | th | ขอถามให้ชัดนะคะ ถูกไฟไหม้หรือน้ำร้อนลวกภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณได้รับบาดเจ็บจากไฟไหม้หรือน้ำร้อนลวกมาใช่ไหมคะ | used |
| confirm_burn_scald_24h | red_flag | en | Just to be sure — did you get a burn or scald within the last 24 hours? | Have you had any burns or scalds in the last 24 hours? | used |
| confirm_cardiac_arrest | red_flag | th | ขอถามให้ชัดนะคะ ผู้ป่วยไม่หายใจและไม่มีชีพจรใช่ไหมคะ | ตอนนี้ผู้ป่วยไม่หายใจและคลำชีพจรไม่ได้เลยใช่ไหมคะ | used |
| confirm_cardiac_arrest | red_flag | en | Just to be sure — is the person not breathing and without a pulse? | I need to be certain, is the person not breathing and do they have no pulse? | used |
| confirm_chest_pain | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้เจ็บหรือแน่นหน้าอกอยู่ไหมคะ | ตอนนี้คุณรู้สึกจุกแน่นใต้ลิ้นปี่ หรือเจ็บแน่นหน้าอกอยู่บ้างไหมคะ | used |
| confirm_chest_pain | red_flag | en | Just to be sure — is your chest hurting or feeling tight right now? | Are you feeling any pain or tightness in your chest at the moment? | used |
| confirm_chest_pain_radiating | red_flag | th | ขอถามให้ชัดนะคะ เจ็บหน้าอกร้าวไปคอ กราม ไหล่ หรือแขนใช่ไหมคะ | ตอนนี้คุณมีอาการเจ็บหน้าอกร้าวไปที่คอ กราม ไหล่ หรือแขนบ้างไหมคะ | used |
| confirm_chest_pain_radiating | red_flag | en | Just to be sure — does the chest pain spread to your neck, jaw, shoulder, or arm? | Does your chest pain spread to your neck, jaw, shoulder, or arm? | used |
| confirm_chronic_cough_2w | red_flag | th | ขอถามให้ชัดนะคะ ไอเรื้อรังมากกว่า 2 สัปดาห์แล้วใช่ไหมคะ | ไม่ทราบว่าคุณมีอาการไอต่อเนื่องมานานเกิน 2 สัปดาห์แล้วใช่ไหมคะ | used |
| confirm_chronic_cough_2w | red_flag | en | Just to be sure — has the cough lasted more than 2 weeks? | Has your cough been going on for more than two weeks? | used |
| confirm_confusion | red_flag | th | ขอถามให้ชัดนะคะ มีอาการซึมหรือสับสนที่เพิ่งเป็นใช่ไหมคะ | ตอนนี้คุณรู้สึกว่าเขามีอาการซึมลง พูดจาสับสน หรือเรียกแล้วตอบช้าลงบ้างไหมคะ | used |
| confirm_confusion | red_flag | en | Just to be sure — is there new confusion or unusual drowsiness? | Are you feeling unusually sleepy or confused today? | used |
| confirm_crowning | red_flag | th | ขอถามให้ชัดนะคะ ทารกกำลังคลอดหรือมีส่วนของทารกโผล่ออกมาแล้วใช่ไหมคะ | ตอนนี้มีส่วนของทารกโผล่ออกมา หรือรู้สึกว่าเด็กกำลังจะคลอดแล้วใช่ไหมคะ | used |
| confirm_crowning | red_flag | en | Just to be sure — is the baby coming now, or can part of the baby be seen? | Is the baby coming out right now, or can you see any part of the baby? | used |
| confirm_decreased_fetal_movement | red_flag | th | ขอถามให้ชัดนะคะ ลูกดิ้นน้อยลงกว่าปกติใช่ไหมคะ | คุณแม่รู้สึกว่าลูกดิ้นน้อยลงกว่าปกติใช่ไหมคะ | used |
| confirm_decreased_fetal_movement | red_flag | en | Just to be sure — is the baby moving less than usual? | Have you noticed the baby moving less than usual lately? | used |
| confirm_dehydration_signs | red_flag | th | ขอถามให้ชัดนะคะ ดื่มน้ำแล้วอาเจียน ปัสสาวะน้อย หรือลุกแล้วหน้ามืดใช่ไหมคะ | ตอนนี้มีอาการดื่มน้ำแล้วอาเจียน ปัสสาวะน้อย หรือลุกขึ้นแล้วรู้สึกหน้ามืดบ้างไหมคะ | used |
| confirm_dehydration_signs | red_flag | en | Just to be sure — can't you keep fluids down, passing little urine, or dizzy on standing? | Are you having trouble keeping fluids down, passing very little urine, or feeling dizzy when you stand up? | used |
| confirm_diaphoresis | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้เหงื่อออกมากหรือเหงื่อแตกอยู่ไหมคะ | ตอนนี้คุณมีอาการเหงื่อแตกท่วมตัวหรือเหงื่อออกมากผิดปกติบ้างไหมคะ | used |
| confirm_diaphoresis | red_flag | en | Just to be sure — are you sweating heavily or in a cold sweat right now? | Are you sweating heavily or feeling a cold sweat right now? | used |
| confirm_diarrhea | red_flag | th | ขอถามให้ชัดนะคะ มีท้องเสียถ่ายเหลวใช่ไหมคะ | ตอนนี้คุณมีอาการท้องเสียหรือถ่ายเหลวอยู่ใช่ไหมคะ | used |
| confirm_diarrhea | red_flag | en | Just to be sure — do you have diarrhea? | Are you currently having any diarrhea or loose stools? | used |
| confirm_dyspnea | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้หายใจเหนื่อยอยู่ไหมคะ | ตอนนี้คุณรู้สึกหายใจเหนื่อย หรือหายใจลำบากบ้างไหมคะ | used |
| confirm_dyspnea | red_flag | en | Just to be sure — are you short of breath right now? | Are you feeling short of breath at the moment? | used |
| confirm_electric_shock_24h | red_flag | th | ขอถามให้ชัดนะคะ ถูกไฟดูดภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | คุณเพิ่งถูกไฟช็อตหรือไฟดูดมาภายใน 24 ชั่วโมงที่ผ่านมานี้ใช่ไหมคะ | used |
| confirm_electric_shock_24h | red_flag | en | Just to be sure — did you get an electric shock within the last 24 hours? | Have you had an electric shock or been electrocuted in the last 24 hours? | used |
| confirm_epistaxis_uncontrolled | red_flag | th | ขอถามให้ชัดนะคะ เลือดกำเดาไหลไม่หยุดอยู่ใช่ไหมคะ | ตอนนี้เลือดกำเดายังไหลไม่หยุดเลยใช่ไหมคะ | used |
| confirm_epistaxis_uncontrolled | red_flag | en | Just to be sure — is the nosebleed still not stopping? | Is your nose still bleeding without stopping? | used |
| confirm_evening_fever | red_flag | th | ขอถามให้ชัดนะคะ มีไข้ต่ำ ๆ ช่วงเย็นใช่ไหมคะ | ช่วงนี้มีอาการไข้ต่ำ ๆ หรือรู้สึกตัวร้อนขึ้นมาบ้างไหมคะในช่วงเย็น | used |
| confirm_evening_fever | red_flag | en | Just to be sure — do you get a low-grade fever in the evenings? | Do you notice your temperature rising slightly in the evenings? | used |
| confirm_eye_active_bleeding | red_flag | th | ขอถามให้ชัดนะคะ มีเลือดออกที่ตาไม่หยุดใช่ไหมคะ | ตอนนี้มีเลือดออกที่ตาไม่หยุดเลยใช่ไหมคะ | used |
| confirm_eye_active_bleeding | red_flag | en | Just to be sure — is the eye bleeding and not stopping? | Is there any bleeding from your eye that just won't stop? | used |
| confirm_eye_chemical_exposure | red_flag | th | ขอถามให้ชัดนะคะ มีสารเคมีหรือพิษสัตว์กระเด็นเข้าตาใช่ไหมคะ | มีสารเคมีหรือพิษสัตว์กระเด็นเข้าตาบ้างไหมคะ | used |
| confirm_eye_chemical_exposure | red_flag | en | Just to be sure — did a chemical or animal venom get into your eye? | Did any chemicals or animal venom get splashed into your eye? | used |
| confirm_eye_trauma | red_flag | th | ขอถามให้ชัดนะคะ เกิดอุบัติเหตุทางตาใช่ไหมคะ | ไม่ทราบว่าดวงตาของคุณได้รับอุบัติเหตุหรือถูกกระแทกมาใช่ไหมคะ | refused: missing:eye_trauma |
| confirm_eye_trauma | red_flag | en | Just to be sure — was there an injury or accident to the eye? | Did you have an accident involving your eye or hurt it in some way? | used |
| confirm_facial_droop | red_flag | th | ขอถามให้ชัดนะคะ ปากเบี้ยวหรือหน้าเบี้ยวแบบฉับพลันใช่ไหมคะ | ตอนนี้มีอาการปากเบี้ยวหรือหน้าเบี้ยวเกิดขึ้นอย่างกะทันหันบ้างไหมคะ | used |
| confirm_facial_droop | red_flag | en | Just to be sure — is one side of the face or mouth drooping, and did it start suddenly? | Is one side of your face or mouth drooping, and did it happen all of a sudden? | used |
| confirm_fatigue_weight_loss | red_flag | th | ขอถามให้ชัดนะคะ อ่อนเพลียและน้ำหนักลดโดยไม่ทราบสาเหตุใช่ไหมคะ | ช่วงนี้คุณรู้สึกอ่อนเพลียหรือน้ำหนักลดลงโดยไม่ทราบสาเหตุบ้างไหมคะ | used |
| confirm_fatigue_weight_loss | red_flag | en | Just to be sure — have you been tired and losing weight without trying? | Have you been feeling very tired and losing weight without trying? | used |
| confirm_fever | red_flag | th | ขอถามให้ชัดนะคะ มีไข้ใช่ไหมคะ | ตอนนี้คุณมีอาการไข้ขึ้นหรือตัวร้อนบ้างไหมคะ | used |
| confirm_fever | red_flag | en | Just to be sure — do you have a fever? | Have you been feeling feverish or had a high temperature lately? | used |
| confirm_floppy_infant | red_flag | th | ขอถามให้ชัดนะคะ เด็กตัวอ่อนปวกเปียกหรือไม่ตอบสนองใช่ไหมคะ | ตอนนี้เด็กมีอาการตัวอ่อนปวกเปียก หรือดูไม่ค่อยตอบสนองบ้างไหมคะ | used |
| confirm_floppy_infant | red_flag | en | Just to be sure — is the child limp or floppy, or not responding? | Is your child limp, floppy, or not responding to you right now? | used |
| confirm_foreign_body_ent_24h | red_flag | th | ขอถามให้ชัดนะคะ มีสิ่งแปลกปลอมติดในหู จมูก หรือคอภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา มีสิ่งของหรือแมลงหลุดเข้าไปในหู จมูก หรือคอของคุณบ้างไหมคะ | used |
| confirm_foreign_body_ent_24h | red_flag | en | Just to be sure — is something stuck in the ear, nose, or throat since the last 24 hours? | Could you tell me if you have something stuck in your ear, nose, or throat? | used |
| confirm_fracture_suspected | red_flag | th | ขอถามให้ชัดนะคะ สงสัยว่ากระดูกหักหรือข้อหลุดใช่ไหมคะ | คุณรู้สึกว่ามีกระดูกหักหรือข้อเคลื่อนหลุดจากที่เดิมบ้างไหมคะ | used |
| confirm_fracture_suspected | red_flag | en | Just to be sure — do you suspect a broken bone or a dislocated joint? | Do you think you might have a broken bone or a joint that popped out of place? | used |
| confirm_ga_24w_or_more | red_flag | th | ขอถามให้ชัดนะคะ อายุครรภ์ 24 สัปดาห์ขึ้นไปใช่ไหมคะ | คุณแม่ตั้งครรภ์ได้ 24 สัปดาห์ขึ้นไปแล้วใช่ไหมคะ | used |
| confirm_ga_24w_or_more | red_flag | en | Just to be sure — is the pregnancy at 24 weeks or more? | Are you at least six months pregnant? | used |
| confirm_gasping | red_flag | th | ขอถามให้ชัดนะคะ หายใจเฮือก ๆ อยู่ใช่ไหมคะ | ตอนนี้คุณมีอาการหายใจเฮือก ๆ หรือหายใจลำบากบ้างไหมคะ | used |
| confirm_gasping | red_flag | en | Just to be sure — is the breathing coming in gasps? | Are you having any trouble catching your breath, or does it feel like you are taking gasping breaths? | used |
| confirm_head_injury | red_flag | th | ขอถามให้ชัดนะคะ ศีรษะกระแทกหรือบาดเจ็บที่ศีรษะใช่ไหมคะ | ไม่ทราบว่าคุณมีอาการบาดเจ็บที่ศีรษะหรือศีรษะกระแทกมาบ้างไหมคะ | used |
| confirm_head_injury | red_flag | en | Just to be sure — did you hit or injure your head? | I need to check one more thing. Did you hit or injure your head recently? | used |
| confirm_headache | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ปวดศีรษะอยู่ไหมคะ | ตอนนี้คุณมีอาการปวดหัวอยู่บ้างไหมคะ | used |
| confirm_headache | red_flag | en | Just to be sure — do you have a headache right now? | Are you feeling any pain in your head right now? | used |
| confirm_headache_sudden_severe | red_flag | th | ขอถามให้ชัดนะคะ ปวดศีรษะรุนแรงฉับพลัน ปวดที่สุดในชีวิตใช่ไหมคะ | ตอนนี้คุณมีอาการปวดหัวรุนแรงมากที่สุดในชีวิตแบบฉับพลันเลยใช่ไหมคะ | used |
| confirm_headache_sudden_severe | red_flag | en | Just to be sure — did a very severe headache come on suddenly, the worst you've ever had? | Did you experience a sudden, very severe headache that felt like the worst one you have ever had? | refused: validator |
| confirm_heart_disease_history | red_flag | th | ขอถามให้ชัดนะคะ มีประวัติโรคหัวใจหรือเส้นเลือดหัวใจตีบใช่ไหมคะ | คุณเคยมีประวัติเป็นโรคหัวใจหรือเส้นเลือดหัวใจตีบมาก่อนบ้างไหมคะ | used |
| confirm_heart_disease_history | red_flag | en | Just to be sure — do you have a history of heart disease or blocked heart arteries? | Have you ever been told by a doctor that you have heart problems or blocked heart arteries? | refused: validator |
| confirm_heavy_vaginal_bleeding | red_flag | th | ขอถามให้ชัดนะคะ เลือดออกทางช่องคลอดมากจนเปียกชุ่มผ้าอนามัยทุกชั่วโมงใช่ไหมคะ | รบกวนสอบถามเพิ่มเติมนะคะว่า มีเลือดออกมากจนต้องเปลี่ยนผ้าอนามัยทุกชั่วโมงเลยไหมคะ | refused: missing:heavy_vaginal_bleeding |
| confirm_heavy_vaginal_bleeding | red_flag | en | Just to be sure — is the vaginal bleeding heavy, soaking a pad every hour? | Are you soaking through a pad every hour because of heavy bleeding? | used |
| confirm_hematemesis | red_flag | th | ขอถามให้ชัดนะคะ ช่วงนี้อาเจียนเป็นเลือดใช่ไหมคะ | ช่วงนี้มีอาการอาเจียนออกมาเป็นเลือดบ้างไหมคะ | used |
| confirm_hematemesis | red_flag | en | Just to be sure — have you vomited blood recently? | Have you thrown up any blood recently? | used |
| confirm_hemoptysis | red_flag | th | ขอถามให้ชัดนะคะ ไอเป็นเลือดหรือมีเสมหะปนเลือดใช่ไหมคะ | คุณมีอาการไอออกมาเป็นเลือด หรือมีเลือดปนออกมากับเสมหะบ้างไหมคะ | used |
| confirm_hemoptysis | red_flag | en | Just to be sure — are you coughing up blood or blood-streaked sputum? | Are you coughing up any blood or seeing blood in your spit? | used |
| confirm_hypertension_history | red_flag | th | ขอถามให้ชัดนะคะ มีโรคความดันโลหิตสูงใช่ไหมคะ | คุณมีโรคประจำตัวเป็นความดันโลหิตสูงอยู่บ้างไหมคะ | used |
| confirm_hypertension_history | red_flag | en | Just to be sure — do you have a history of high blood pressure? | Do you have a history of high blood pressure? | used |
| confirm_hypoglycemia_symptoms | red_flag | th | ขอถามให้ชัดนะคะ มีอาการน้ำตาลต่ำ เช่น มือสั่น เหงื่อแตก มึนงง หิวมาก ใช่ไหมคะ | ช่วงนี้มีอาการเหมือนน้ำตาลตก เช่น มือสั่น เหงื่อออกเยอะ หรือรู้สึกหิวผิดปกติบ้างไหมคะ | used |
| confirm_hypoglycemia_symptoms | red_flag | en | Just to be sure — do you feel shaky, sweaty, confused, or very hungry, like low blood sugar? | Are you feeling shaky, sweaty, confused, or unusually hungry right now? | used |
| confirm_immediate_danger | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ยังอยู่ในอันตรายหรือผู้ก่อเหตุอยู่ใกล้ ๆ ใช่ไหมคะ | ตอนนี้คุณยังอยู่ในที่ที่อันตราย หรือมีคนทำร้ายอยู่ใกล้ ๆ คุณไหมคะ | used |
| confirm_immediate_danger | red_flag | en | Just to be sure — are you still in immediate danger, or is the attacker nearby? | Are you currently in a safe place, or is there still a risk of someone hurting you nearby? | used |
| confirm_injury_within_24h | red_flag | th | ขอถามให้ชัดนะคะ บาดเจ็บภายใน 24 ชั่วโมงที่ผ่านมาใช่ไหมคะ | คุณได้รับบาดเจ็บภายในร่างกายในช่วง 24 ชั่วโมงที่ผ่านมานี้ใช่ไหมคะ | used |
| confirm_injury_within_24h | red_flag | en | Just to be sure — did the injury happen within the last 24 hours? | Did this injury happen within the last 24 hours? | used |
| confirm_limb_ischemia | red_flag | th | ขอถามให้ชัดนะคะ มือเท้าเย็น ปวด ซีดดำ หรือมีแผลเรื้อรังที่แขนขาใช่ไหมคะ | รบกวนสอบถามเพิ่มเติมนะคะว่า มีอาการปวดเวลาขยับแขนขา แขนขาซีดเย็น หรือมีแผลเรื้อรังบ้างไหมคะ | used |
| confirm_limb_ischemia | red_flag | en | Just to be sure — are your hands or feet cold, painful, or discolored, or is there a wound that won't heal? | Are your hands or feet feeling cold, looking a different color, or do you have any sores that aren't healing? | used |
| confirm_limb_weakness | red_flag | th | ขอถามให้ชัดนะคะ แขนขาอ่อนแรงหรือชาครึ่งซีกแบบฉับพลันใช่ไหมคะ | ตอนนี้มีอาการแขนขาอ่อนแรงหรือชาครึ่งซีกแบบฉับพลันบ้างไหมคะ | used |
| confirm_limb_weakness | red_flag | en | Just to be sure — did an arm or leg suddenly go weak or numb on one side? | Did you suddenly feel any weakness or numbness in your arm or leg on one side of your body? | used |
| confirm_lip_swelling | red_flag | th | ขอถามให้ชัดนะคะ ปากบวมหรือหน้าบวมอยู่ใช่ไหมคะ | ตอนนี้มีอาการปากบวมหรือหน้าบวมอยู่บ้างไหมคะ | used |
| confirm_lip_swelling | red_flag | en | Just to be sure — are your lips, mouth, or face swelling? | Are you noticing any swelling around your lips, mouth, or face? | used |
| confirm_loc_transient | red_flag | th | ขอถามให้ชัดนะคะ หมดสติหรือสลบชั่วครู่หลังศีรษะกระแทกหรือบาดเจ็บใช่ไหมคะ | หลังจากที่ศีรษะกระแทกหรือได้รับบาดเจ็บ คุณเคยหมดสติหรือสลบไปบ้างไหมคะ | used |
| confirm_loc_transient | red_flag | en | Just to be sure — were you knocked out, even briefly, after hitting your head or getting injured? | Did you black out for even a second after you hit your head? | used |
| confirm_major_trauma_mechanism | red_flag | th | ขอถามให้ชัดนะคะ เป็นอุบัติเหตุรถยนต์หรือจักรยานยนต์ ตกจากที่สูงเกิน 5 เมตร หรือถูกรถชนใช่ไหมคะ | คุณได้รับบาดเจ็บจากอุบัติเหตุรถชน ตกจากที่สูง หรือรถยนต์ชนมาใช่ไหมคะ | used |
| confirm_major_trauma_mechanism | red_flag | en | Just to be sure — was it a car or motorcycle accident, a fall from over 5 metres, or were you hit by a vehicle? | Did you have a motorcycle accident, a fall from over 5 metres, or were you hit by a vehicle as a pedestrian? | used |
| confirm_melena | red_flag | th | ขอถามให้ชัดนะคะ ช่วงนี้ถ่ายดำใช่ไหมคะ | ช่วงนี้คุณมีอาการถ่ายอุจจาระเป็นสีดำบ้างไหมคะ | used |
| confirm_melena | red_flag | en | Just to be sure — has your stool been black and tarry recently? | Have you noticed your stool looking black or tarry lately? | used |
| confirm_missed_period | red_flag | th | ขอถามให้ชัดนะคะ ประจำเดือนขาดใช่ไหมคะ | ขอทราบหน่อยค่ะว่าประจำเดือนของคุณขาดไปนานหรือยังคะ | used |
| confirm_missed_period | red_flag | en | Just to be sure — have you missed a period? | Could you tell me if you have missed your period? | used |
| confirm_nasal_flaring | red_flag | th | ขอถามให้ชัดนะคะ เด็กหายใจปีกจมูกบานใช่ไหมคะ | คุณแม่ช่วยสังเกตหน่อยนะคะว่า เวลาที่น้องหายใจ ปีกจมูกของน้องมีการขยับบานออกด้วยไหมคะ | used |
| confirm_nasal_flaring | red_flag | en | Just to be sure — are the child's nostrils flaring when they breathe? | Are the child's nostrils widening or flaring when they take a breath? | used |
| confirm_neck_swelling_dysphagia | red_flag | th | ขอถามให้ชัดนะคะ คอบวมโตร่วมกับกลืนลำบากหรือหายใจลำบากใช่ไหมคะ | คุณมีอาการคอบวมโต กลืนลำบาก หรือหายใจลำบากบ้างไหมคะ | used |
| confirm_neck_swelling_dysphagia | red_flag | en | Just to be sure — is the neck swollen with trouble swallowing or breathing? | Is your neck swollen, and are you having any trouble swallowing or breathing? | used |
| confirm_overdose_or_poison | red_flag | th | ขอถามให้ชัดนะคะ ได้รับยาเกินขนาดหรือสัมผัสสารพิษหรือสารเคมีใช่ไหมคะ | ไม่ทราบว่าคุณได้รับยาเกินขนาด หรือสัมผัสสารเคมีหรือสารพิษมาบ้างไหมคะ | used |
| confirm_overdose_or_poison | red_flag | en | Just to be sure — was there a drug overdose, or contact with poison or chemicals? | I need to check if you have been exposed to any poisons, chemicals, or taken too many pills. | refused: question_count |
| confirm_pale_cold_sweaty | red_flag | th | ขอถามให้ชัดนะคะ ผิวหนังซีดและตัวเย็นชื้นพร้อมกันใช่ไหมคะ | ตอนนี้มีอาการหน้าซีดและตัวเย็นชื้นพร้อมกันบ้างไหมคะ | used |
| confirm_pale_cold_sweaty | red_flag | en | Just to be sure — is the skin pale, cold, and clammy all at once? | Is your skin feeling pale, cold, and clammy all at the same time? | used |
| confirm_palm_sole_rash | red_flag | th | ขอถามให้ชัดนะคะ มีผื่นแดงตามฝ่ามือ ฝ่าเท้า หรือรอบปากใช่ไหมคะ | ตอนนี้มีผื่นแดงขึ้นตามฝ่ามือ ฝ่าเท้า หรือรอบปากบ้างไหมคะ | used |
| confirm_palm_sole_rash | red_flag | en | Just to be sure — is there a red rash on the palms, soles, or around the mouth? | Do you have a red rash on your palms, soles, or around your mouth? | used |
| confirm_palpitations | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ใจสั่นหรือหัวใจเต้นเร็วผิดปกติอยู่ไหมคะ | ตอนนี้คุณรู้สึกว่าหัวใจเต้นเร็วผิดปกติ หรือใจสั่นรัวอยู่บ้างไหมคะ | used |
| confirm_palpitations | red_flag | en | Just to be sure — do you have palpitations or a racing heart right now? | Are you feeling your heart racing or pounding right now? | used |
| confirm_penetrating_injury_torso | red_flag | th | ขอถามให้ชัดนะคะ ถูกแทงที่คอ หน้าอก หรือช่องท้องใช่ไหมคะ | คุณถูกแทงที่บริเวณคอ หน้าอก หรือช่องท้องใช่ไหมคะ | used |
| confirm_penetrating_injury_torso | red_flag | en | Just to be sure — is there a stab or penetrating wound to the neck, chest, or abdomen? | I need to check one more thing. Do you have any stab or penetrating wounds on your neck, chest, or stomach? | used |
| confirm_pregnancy | red_flag | th | ขอถามให้ชัดนะคะ กำลังตั้งครรภ์อยู่ใช่ไหมคะ | ไม่ทราบว่าตอนนี้คุณกำลังตั้งครรภ์อยู่ไหมคะ | used |
| confirm_pregnancy | red_flag | en | Just to be sure — are you currently pregnant? | Are you currently expecting a baby? | used |
| confirm_rash_itching | red_flag | th | ขอถามให้ชัดนะคะ มีผื่นคันหรือลมพิษใช่ไหมคะ | ตอนนี้มีอาการผื่นคันหรือลมพิษขึ้นตามตัวบ้างไหมคะ | used |
| confirm_rash_itching | red_flag | en | Just to be sure — do you have an itchy rash or hives? | Are you currently dealing with an itchy rash or hives? | used |
| confirm_rash_rapidly_spreading | red_flag | th | ขอถามให้ชัดนะคะ ผื่นลามเร็วภายในไม่กี่ชั่วโมงใช่ไหมคะ | ผื่นของคุณลามเร็วขึ้นภายในไม่กี่ชั่วโมงหรือเปล่าคะ | used |
| confirm_rash_rapidly_spreading | red_flag | en | Just to be sure — is the rash spreading rapidly, within hours? | Is the rash spreading quickly, like within just a few hours? | used |
| confirm_recent_chemotherapy | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้ได้รับยาเคมีบำบัดอยู่ใช่ไหมคะ | ตอนนี้คุณกำลังรับยาเคมีบำบัดอยู่ใช่ไหมคะ | used |
| confirm_recent_chemotherapy | red_flag | en | Just to be sure — are you currently receiving chemotherapy? | Are you currently receiving chemotherapy? | used |
| confirm_retraction | red_flag | th | ขอถามให้ชัดนะคะ หายใจแล้วมีอกบุ๋มใช่ไหมคะ | เวลาหายใจเข้าแรง ๆ สังเกตเห็นว่ามีร่องซี่โครงหรือหน้าอกบุ๋มลงไปบ้างไหมคะ | used |
| confirm_retraction | red_flag | en | Just to be sure — do the spaces between the ribs or at the neck pull in when breathing (retractions)? | Do you notice the skin between the ribs or at the neck pulling in when breathing? | used |
| confirm_seizure_now | red_flag | th | ขอถามให้ชัดนะคะ ตอนนี้กำลังชักเกร็งและเรียกไม่รู้สึกตัวใช่ไหมคะ | ตอนนี้ผู้ป่วยกำลังมีอาการชักเกร็งหรือเรียกไม่รู้สึกตัวอยู่ใช่ไหมคะ | used |
| confirm_seizure_now | red_flag | en | Just to be sure — is the person having a seizure right now, convulsing and not responding? | Is the person having a seizure right now, or are they convulsing and not responding? | used |
| confirm_self_harm_risk | red_flag | th | ขอถามให้ชัดนะคะ มีความเสี่ยงทำร้ายตนเองหรือผู้อื่น หรือเพิ่งทำร้ายตนเองมาใช่ไหมคะ | ช่วงนี้คุณมีความคิดอยากทำร้ายตัวเองหรือผู้อื่นบ้างไหมคะ หรือว่าเพิ่งเกิดเหตุการณ์ทำร้ายตัวเองมาหรือเปล่าคะ | used |
| confirm_self_harm_risk | red_flag | en | Just to be sure — is there a risk of harming yourself or others, or recent self-harm? | I need to ask if you have any thoughts about hurting yourself or others, or if you have done so recently. | refused: question_count |
| confirm_severe_morning_sickness | red_flag | th | ขอถามให้ชัดนะคะ แพ้ท้องรุนแรงจนกินไม่ได้เลยใช่ไหมคะ | คุณมีอาการแพ้ท้องหนักจนทานอาหารหรือดื่มน้ำไม่ได้เลยใช่ไหมคะ | used |
| confirm_severe_morning_sickness | red_flag | en | Just to be sure — is the pregnancy vomiting so severe you can't eat or drink? | Are you finding that your pregnancy vomiting is so severe that you cannot keep any food or drinks down? | used |
| confirm_severe_respiratory_distress | red_flag | th | ขอถามให้ชัดนะคะ หายใจลำบากรุนแรงจนพูดเป็นประโยคไม่ได้หรือต้องลุกนั่งหายใจใช่ไหมคะ | ตอนนี้คุณหายใจลำบากจนพูดเป็นประโยคไม่ได้ หรือต้องลุกนั่งเพื่อให้หายใจสะดวกขึ้นบ้างไหมคะ | used |
| confirm_severe_respiratory_distress | red_flag | en | Just to be sure — is the breathing difficulty severe, so you can't speak full sentences or must sit up to breathe? | Are you having a hard time breathing, like not being able to finish a sentence or needing to sit upright to catch your breath? | used |
| confirm_sexual_assault_72h | red_flag | th | ขอถามให้ชัดนะคะ ถูกกระทำชำเราภายใน 72 ชั่วโมงที่ผ่านมาใช่ไหมคะ | ขอสอบถามเพื่อความชัดเจนนะคะ คุณถูกกระทำชำเราภายใน 72 ชั่วโมงที่ผ่านมาใช่หรือไม่คะ | used |
| confirm_sexual_assault_72h | red_flag | en | Just to be sure — was there a sexual assault within the last 72 hours? | I need to ask, has there been a sexual assault within the last three days? | used |
| confirm_slurred_speech | red_flag | th | ขอถามให้ชัดนะคะ พูดไม่ชัดหรือลิ้นแข็งแบบทันทีทันใดใช่ไหมคะ | ตอนนี้คุณมีอาการพูดไม่ชัด พูดไม่ออก หรือพูดอ้อแอ้แบบกะทันหันบ้างไหมคะ | used |
| confirm_slurred_speech | red_flag | en | Just to be sure — did your speech suddenly become slurred or garbled? | Has your speech suddenly become slurred or hard to understand? | used |
| confirm_stiff_neck | red_flag | th | ขอถามให้ชัดนะคะ คอแข็งร่วมกับไข้ใช่ไหมคะ | ตอนนี้คุณมีอาการคอแข็งหรือก้มคอไม่ได้บ้างไหมคะ | used |
| confirm_stiff_neck | red_flag | en | Just to be sure — is your neck stiff along with the fever? | Are you feeling a stiff neck along with your fever? | used |
| confirm_sudden_vision_loss | red_flag | th | ขอถามให้ชัดนะคะ ตามองไม่เห็นเฉียบพลันหรือเห็นภาพซ้อนใช่ไหมคะ | ตอนนี้มีอาการตามองไม่เห็นกะทันหัน หรือเห็นภาพซ้อนบ้างไหมคะ | used |
| confirm_sudden_vision_loss | red_flag | en | Just to be sure — did you suddenly lose vision, or start seeing double? | Have you noticed any sudden loss of vision or are you seeing double? | used |
| confirm_suicidal_ideation | red_flag | th | ขอถามให้ชัดนะคะ มีความคิดอยากตายหรืออยากฆ่าตัวตายใช่ไหมคะ | ช่วงนี้คุณมีความคิดอยากตายหรืออยากทำร้ายตัวเองบ้างไหมคะ | used |
| confirm_suicidal_ideation | red_flag | en | Just to be sure — have you had thoughts of suicide or wanting to die? | Have you been having any thoughts about ending your life? | used |
| confirm_syncope_24h | red_flag | th | ขอถามให้ชัดนะคะ วูบ หน้ามืด หรือเป็นลมภายใน 24 ชั่วโมงที่ผ่านมา โดยไม่ได้เกิดจากอุบัติเหตุใช่ไหมคะ | ในช่วง 24 ชั่วโมงที่ผ่านมา คุณมีอาการวูบ หน้ามืด หรือหมดสติไปโดยไม่ได้เกิดจากอุบัติเหตุบ้างไหมคะ | used |
| confirm_syncope_24h | red_flag | en | Just to be sure — did you faint or nearly faint within the last 24 hours, without an injury causing it? | Have you fainted or felt like you were going to pass out in the last day, without any injury causing it? | used |
| confirm_unilateral_leg_swelling | red_flag | th | ขอถามให้ชัดนะคะ ขาบวมและปวดข้างเดียวใช่ไหมคะ | ตอนนี้คุณมีอาการขาบวมหรือปวดแค่ข้างเดียวใช่ไหมคะ | used |
| confirm_unilateral_leg_swelling | red_flag | en | Just to be sure — is one leg swollen and painful? | Is one of your legs swollen and painful right now? | used |
| confirm_unresponsive | red_flag | th | ขอถามให้ชัดนะคะ ผู้ป่วยซึมลงปลุกไม่ตื่นหรือไม่รู้สึกตัวใช่ไหมคะ | ตอนนี้ผู้ป่วยมีอาการซึมลง ปลุกไม่ตื่น หรือไม่รู้สึกตัวบ้างไหมคะ | used |
| confirm_unresponsive | red_flag | en | Just to be sure — is the person unresponsive and can't be woken? | I need to check one more thing. Is the person unresponsive or unable to be woken up? | used |
| confirm_uterine_contractions_frequent | red_flag | th | ขอถามให้ชัดนะคะ ท้องแข็งเจ็บครรภ์ถี่ประมาณทุก 2 นาทีใช่ไหมคะ | ตอนนี้คุณแม่รู้สึกว่าท้องแข็งหรือเจ็บครรภ์ถี่ประมาณทุก 2 นาทีเลยใช่ไหมคะ | used |
| confirm_uterine_contractions_frequent | red_flag | en | Just to be sure — are the contractions strong and frequent, about every 2 minutes? | Are you having strong contractions about every two minutes? | used |
| confirm_vaginal_bleeding | red_flag | th | ขอถามให้ชัดนะคะ มีเลือดออกทางช่องคลอดผิดปกติใช่ไหมคะ | ตอนนี้คุณมีเลือดออกทางช่องคลอดผิดปกติบ้างไหมคะ | used |
| confirm_vaginal_bleeding | red_flag | en | Just to be sure — is there abnormal vaginal bleeding? | Are you experiencing any abnormal bleeding down there? | used |
| confirm_vomiting | red_flag | th | ขอถามให้ชัดนะคะ มีอาเจียนใช่ไหมคะ | ตอนนี้มีอาการคลื่นไส้หรืออาเจียนบ้างไหมคะ | used |
| confirm_vomiting | red_flag | en | Just to be sure — are you vomiting? | Are you currently throwing up or feeling sick to your stomach? | used |
| confirm_wound_infection_signs | red_flag | th | ขอถามให้ชัดนะคะ แผลมีอาการติดเชื้อ เช่น แดงลาม มีหนอง หรือร้อน ใช่ไหมคะ | แผลของคุณมีอาการบวมแดง ร้อน หรือมีหนองไหลออกมาบ้างไหมคะ | used |
| confirm_wound_infection_signs | red_flag | en | Just to be sure — does the wound look infected, with spreading redness, pus, or warmth? | Is the area around your wound looking red, feeling warm, or leaking any fluid? | used |
