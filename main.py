from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.clock import Clock
from datetime import datetime, timedelta
import csv, os, holidays
from plyer import notification

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

# ---------------- CONFIG ----------------
FILENAME = "attendance.csv"
FOLDER_NAME = "Attendance Backup"

india_holidays = holidays.India()
VACATIONS = [("15-05-2026", "30-06-2026"), ("20-12-2026", "05-01-2027")]
REMINDER_HOUR = 7
REMINDER_MINUTE = 0

# ---------------- DATE HELPERS ----------------
def is_vacation(date_obj):
    for start, end in VACATIONS:
        if datetime.strptime(start, "%d-%m-%Y") <= date_obj <= datetime.strptime(end, "%d-%m-%Y"):
            return True
    return False

def is_school_day(date_obj):
    return not (date_obj.weekday() == 6 or date_obj in india_holidays or is_vacation(date_obj))

def get_attendance_dict():
    data = {}
    if os.path.exists(FILENAME):
        with open(FILENAME) as f:
            for row in csv.DictReader(f):
                if "Synced" not in row:
                    data[row["Date"]] = {"Status": row["Status"], "Synced": True}
                else:
                    data[row["Date"]] = {"Status": row["Status"], "Synced": row["Synced"]=="True"}
    return data

# ---------------- GOOGLE DRIVE BACKUP ----------------
def get_drive():
    gauth = GoogleAuth()
    gauth.LoadCredentialsFile("credentials.json")
    if gauth.credentials is None:
        gauth.LocalWebserverAuth()  # Opens browser for login
        gauth.SaveCredentialsFile("credentials.json")
    elif gauth.access_token_expired:
        gauth.Refresh()
        gauth.SaveCredentialsFile("credentials.json")
    else:
        gauth.Authorize()
    drive = GoogleDrive(gauth)
    return drive

def get_folder_id(drive, folder_name):
    folder_list = drive.ListFile({
        'q': f"title='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    }).GetList()
    if folder_list:
        return folder_list[0]['id']
    else:
        folder = drive.CreateFile({'title': folder_name, 'mimeType':'application/vnd.google-apps.folder'})
        folder.Upload()
        return folder['id']

def upload_to_drive():
    try:
        drive = get_drive()
        folder_id = get_folder_id(drive, FOLDER_NAME)

        file_list = drive.ListFile({
            'q': f"'{folder_id}' in parents and title='attendance_backup.csv' and trashed=false"
        }).GetList()

        if file_list:
            file_drive = file_list[0]
        else:
            file_drive = drive.CreateFile({'title':'attendance_backup.csv','parents':[{'id':folder_id}]})

        file_drive.SetContentFile(FILENAME)
        file_drive.Upload()
        print("Drive backup updated")

        # Mark all records as synced
        if os.path.exists(FILENAME):
            rows = []
            with open(FILENAME) as f:
                for r in csv.DictReader(f):
                    r["Synced"] = "True"
                    rows.append(r)
            with open(FILENAME, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["Date","Day","Status","Synced"])
                writer.writeheader()
                writer.writerows(rows)

    except Exception as e:
        print("Drive backup failed:", e)

# ---------------- REMINDER ----------------
def check_for_reminder(dt):
    now = datetime.now()
    if now.hour == REMINDER_HOUR and now.minute == REMINDER_MINUTE:
        if is_school_day(now):
            notification.notify(title="Attendance Reminder 📚",
                                message="Mark your attendance for today!", timeout=10)

# ---------------- MAIN LAYOUT ----------------
class MainLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
        self.add_widget(Label(text="Smart Attendance App", size_hint=(1,0.15)))
        self.add_widget(Button(text="Present", on_press=lambda x:self.mark("Present")))
        self.add_widget(Button(text="Absent", on_press=lambda x:self.mark("Absent")))
        self.add_widget(Button(text="View Attendance %", on_press=self.summary))
        self.add_widget(Button(text="Open Calendar View", on_press=self.open_calendar))
        self.add_widget(Button(text="Sync to Drive", on_press=lambda x:self.sync_drive()))
        Clock.schedule_interval(check_for_reminder, 60)

    def popup(self, msg):
        Popup(title="Attendance", content=Label(text=msg), size_hint=(0.8,0.4)).open()

    def mark(self, status):
        today = datetime.today()
        if not is_school_day(today):
            self.popup("No school today!")
            return

        date_str = today.strftime("%d-%m-%Y")
        day_name = today.strftime("%A")

        if os.path.exists(FILENAME):
            with open(FILENAME) as f:
                if any(row["Date"]==date_str for row in csv.DictReader(f)):
                    self.popup("Already marked!")
                    return

        with open(FILENAME, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["Date","Day","Status","Synced"])
            if os.stat(FILENAME).st_size==0:
                writer.writeheader()
            writer.writerow({"Date":date_str,"Day":day_name,"Status":status,"Synced":False})

        upload_to_drive()
        self.popup(f"{day_name} marked as {status} & Synced!")

    def summary(self, instance):
        if not os.path.exists(FILENAME):
            self.popup("No data")
            return

        total=present=0
        with open(FILENAME) as f:
            for r in csv.DictReader(f):
                total+=1
                if r["Status"]=="Present": present+=1

        percent = (present/total)*100 if total else 0
        self.popup(f"Attendance: {percent:.1f}%")

    def open_calendar(self, instance):
        popup = Popup(title="Monthly Calendar", size_hint=(0.95,0.9))
        popup.content = CalendarView()
        popup.open()

    def sync_drive(self):
        if not os.path.exists(FILENAME):
            self.popup("No attendance data to sync!")
            return
        upload_to_drive()
        self.popup("Attendance synced to Google Drive ✅")

# ---------------- CALENDAR VIEW ----------------
class CalendarView(GridLayout):
    def __init__(self, **kwargs):
        super().__init__(cols=7, **kwargs)
        self.build_calendar()

    def build_calendar(self):
        attendance = get_attendance_dict()
        today = datetime.today()
        first_day = today.replace(day=1)
        start_day = first_day - timedelta(days=first_day.weekday())

        for i in range(42):
            day = start_day + timedelta(days=i)
            date_str = day.strftime("%d-%m-%Y")
            btn = Button(text=str(day.day))

            if date_str in attendance:
                record = attendance[date_str]
                if record["Status"]=="Absent":
                    btn.background_color=(1,0,0,1)
                elif record["Status"]=="Present":
                    btn.background_color=(0,1,0,1) if record["Synced"] else (1,1,0,1)
            elif not is_school_day(day):
                btn.background_color=(0.5,0.5,0.5,1)

            self.add_widget(btn)

# ---------------- APP ----------------
class AttendanceApp(App):
    def build(self):
        return MainLayout()

AttendanceApp().run()
