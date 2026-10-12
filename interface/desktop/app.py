"""JARVIS Stage 8.1 HUD redesign. Offline-only; never executes commands."""
from __future__ import annotations
import sys
from datetime import datetime
from PySide6.QtCore import Qt, QTimer
from .chat import ChatPage
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QKeyEvent
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
    QGridLayout, QProgressBar, QSizePolicy)

BG='#070405'; PANEL='#11090a'; RED='#e24a3c'; AMBER='#f0a34b'; DIM='#9b6661'
STYLE=f'''
QWidget {{background:{BG};color:#e7c5ba;font-family:'Consolas','Segoe UI';font-size:12px;}}
QFrame#panel {{background:{PANEL};border:1px solid #54201d;border-radius:9px;}}
QFrame#sidebar {{background:#0e0708;border-right:1px solid #54201d;}}
QLabel#brand {{font-size:24px;font-weight:800;color:{RED};letter-spacing:3px;}}
QLabel#section {{color:{RED};font-size:12px;font-weight:bold;letter-spacing:2px;}}
QLabel#muted {{color:{DIM};}}
QLabel#title {{color:#f1b39e;font-size:20px;font-weight:bold;}}
QPushButton {{background:#1a0c0d;border:1px solid #612520;color:#e5b6a9;border-radius:5px;padding:10px;text-align:left;}}
QPushButton:hover {{background:#3a1414;border-color:{RED};}}
QPushButton:checked {{background:#481714;color:#ffb39e;border-color:{RED};}}
QPushButton#send {{background:#a52e26;color:#fff;text-align:center;font-weight:bold;}}
QLineEdit {{background:#170c0c;border:1px solid #60241e;border-radius:5px;padding:12px;color:#ffe1d2;}}
QLineEdit:focus {{border:1px solid {AMBER};}}
QTextEdit {{background:#0b0607;border:1px solid #49201c;border-radius:5px;padding:12px;color:#dcb5a8;}}
QProgressBar {{border:0;background:#311513;height:5px;text-align:center;}}
QProgressBar::chunk {{background:{RED};}}
'''

def label(text, obj=None, wrap=False):
    w=QLabel(text)
    if obj: w.setObjectName(obj)
    w.setWordWrap(wrap)
    return w

def panel(title):
    outer=QFrame();outer.setObjectName('panel')
    col=QVBoxLayout(outer);col.setContentsMargins(14,12,14,12);col.setSpacing(9)
    col.addWidget(label('⌁  '+title.upper(),'section'))
    return outer,col

class Core(QWidget):
    def __init__(self):
        super().__init__();self.phase=0;self.setMinimumSize(260,260)
        self.timer=QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(45)
    def tick(self):
        self.phase=(self.phase+1)%360;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x=self.width()/2;y=self.height()/2;r=min(self.width(),self.height())*.39
        for frac,color,width,start,span in [(.99,'#3b1716',1,0,360),(.84,'#67271e',2,self.phase,235),(.68,'#a85b26',2,-self.phase*1.3,205),(.52,'#48221a',1,self.phase*.7,300)]:
            p.setPen(QPen(QColor(color),width));p.drawArc(int(x-r*frac),int(y-r*frac),int(2*r*frac),int(2*r*frac),int(start*16),int(span*16))
        p.setPen(QPen(QColor('#6a3025'),1));p.setBrush(QColor('#130909'));p.drawEllipse(int(x-r*.34),int(y-r*.34),int(r*.68),int(r*.68))
        p.setPen(QColor(AMBER));font=QFont('Consolas',max(10,int(r*.12)));font.setBold(True);p.setFont(font)
        p.drawText(int(x-r*.45),int(y-18),int(r*.9),25,Qt.AlignmentFlag.AlignCenter,'J.A.R.V.I.S')
        p.setPen(QColor(DIM));p.setFont(QFont('Consolas',9));p.drawText(int(x-r*.4),int(y+10),int(r*.8),20,Qt.AlignmentFlag.AlignCenter,'OFFLINE // IDLE')
        p.end()

class Dashboard(QWidget):
    def __init__(self, send_callback):
        super().__init__();self.send_callback=send_callback
        root=QVBoxLayout(self);root.setContentsMargins(22,18,22,18);root.setSpacing(12)
        top=QHBoxLayout();top.addWidget(label('STARK // JARVIS COMMAND CENTER','title'));top.addStretch();top.addWidget(label('● HYBRID CHAT / NO TOOLS','muted'));root.addLayout(top)
        grid=QGridLayout();grid.setSpacing(12);root.addLayout(grid,1)
        tasks,tc=panel('Task Intel');tc.addWidget(label('SYSTEM READY','muted'))
        for name in ['◈  System diagnostics','◈  Memory operations','◈  Application control']:
            b=QPushButton(name);b.clicked.connect(lambda _,n=name:self._quick(n));tc.addWidget(b)
        tc.addStretch();grid.addWidget(tasks,0,0)
        activity,ac=panel('Neural Activity');self.activity=label('[READY] Offline interface initialized\n[SECURE] No tools are connected\n[INFO] Awaiting user input','muted',True);self.activity.setAlignment(Qt.AlignmentFlag.AlignTop);ac.addWidget(self.activity,1);grid.addWidget(activity,1,0)
        center=QFrame();cl=QVBoxLayout(center);cl.addWidget(label('SCREEN CONTEXT: NOT CONNECTED','muted'));cl.addWidget(Core(),1);state=label('◈  AWAITING COMMAND','section');state.setAlignment(Qt.AlignmentFlag.AlignCenter);cl.addWidget(state);grid.addWidget(center,0,1,2,1)
        diag,dc=panel('System Diagnostics');dc.addWidget(label('SIMULATED DISPLAY — NO LIVE TELEMETRY','muted'))
        for name,val in [('CPU LOAD',32),('RAM USAGE',64),('DISK',47)]:
            line=QHBoxLayout();line.addWidget(label(name,'muted'));line.addStretch();line.addWidget(label(f'{val}%','muted'));dc.addLayout(line)
            bar=QProgressBar();bar.setRange(0,100);bar.setValue(val);bar.setTextVisible(False);dc.addWidget(bar)
        dc.addStretch();grid.addWidget(diag,0,2)
        mem,mc=panel('Memory Core');mc.addWidget(label('SQLite backend: NOT CONNECTED','muted'));mc.addWidget(label('Stage 7 integration pending','muted'));mc.addStretch();grid.addWidget(mem,1,2)
        grid.setColumnStretch(0,3);grid.setColumnStretch(1,5);grid.setColumnStretch(2,3)
        console,cc=panel('Command Console');row=QHBoxLayout();self.entry=QLineEdit();self.entry.setPlaceholderText('Enter a command (offline preview)...');self.entry.returnPressed.connect(self.send)
        row.addWidget(self.entry,1);send=QPushButton('TRANSMIT');send.setObjectName('send');send.clicked.connect(self.send);row.addWidget(send);cc.addLayout(row)
        self.response=label('No commands executed. Offline UI demonstration only.','muted',True);cc.addWidget(self.response);root.addWidget(console)
    def _quick(self,name):
        self.entry.setText(name.replace('◈  ','').lower());self.entry.setFocus()
    def send(self):
        text=self.entry.text().strip()
        if not text:return
        self.response.setText('YOU: '+text+'\nJARVIS: Routed to Chat screen (chat-only).')
        self.activity.setText('[INPUT] User command received\n[SAFE] Execution disabled in preview\n[READY] Awaiting next input')
        self.entry.clear();self.send_callback(text)

class JarvisWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.setWindowTitle('JARVIS — STARK HUD (Hybrid Chat)');self.resize(1280,800);self.setMinimumSize(980,650);self.setStyleSheet(STYLE)
        root=QWidget();self.setCentralWidget(root);layout=QHBoxLayout(root);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(190);sl=QVBoxLayout(side);sl.setContentsMargins(14,24,14,20)
        sl.addWidget(label('◉ JARVIS','brand'));sl.addWidget(label('MARK VIII // STANDBY','muted'));sl.addSpacing(28)
        self.pages=QStackedWidget();self.buttons=[]
        names=['Dashboard','Chat','Memory','System','Security','Settings']
        for i,name in enumerate(names):
            b=QPushButton(f'  {name.upper()}');b.setCheckable(True);b.clicked.connect(lambda _,idx=i:self.navigate(idx));sl.addWidget(b);self.buttons.append(b)
        sl.addStretch();sl.addWidget(label('SECURITY GATEWAY\nNOT CONNECTED','muted'));layout.addWidget(side)
        self.dashboard=Dashboard(self.record_message);self.pages.addWidget(self.dashboard)
        self.chat_page=ChatPage()
        self.pages.addWidget(self.chat_page)
        for title,description in [('MEMORY CORE','Memory management will use the trusted Stage 7 gateway.'),('SYSTEM DIAGNOSTICS','Real metrics will use existing authorized system tools.'),('SECURITY CONTROL','Confirmations will use the existing Stage 4 gateway.'),('CONFIGURATION','Provider and interface settings will appear here.')]:
            page=QWidget();col=QVBoxLayout(page);col.setContentsMargins(32,32,32,32);col.addWidget(label(title,'title'));col.addWidget(label(description,'muted',True));col.addStretch();self.pages.addWidget(page)
        layout.addWidget(self.pages,1);self.navigate(0)
    def navigate(self,index):
        self.pages.setCurrentIndex(index)
        for i,b in enumerate(self.buttons):b.setChecked(i==index)
    def record_message(self,text):
        self.chat_page.input.setPlainText(text)
        self.chat_page.submit()
        self.navigate(1)
    def closeEvent(self,event):
        self.chat_page.shutdown()
        super().closeEvent(event)

def main():
    app=QApplication.instance() or QApplication(sys.argv)
    window=JarvisWindow();window.show();return app.exec()

if __name__=='__main__':raise SystemExit(main())
