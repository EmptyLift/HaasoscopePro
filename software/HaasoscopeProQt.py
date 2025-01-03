import numpy as np
import sys, time, warnings
import pyqtgraph as pg
import PyQt5
from pyqtgraph.Qt import QtCore, QtWidgets, loadUiType
from PyQt5.QtGui import QPalette, QColor
from scipy.optimize import curve_fit
from usbs import *
from board import *

usbs = connectdevices()
if len(usbs)==0: sys.exit(0)
usbs = orderusbs(usbs)

# Define fft window class from template
FFTWindowTemplate, FFTTemplateBaseClass = loadUiType("HaasoscopeProFFT.ui")
class FFTWindow(FFTTemplateBaseClass):
    def __init__(self):
        FFTTemplateBaseClass.__init__(self)
        self.ui = FFTWindowTemplate()
        self.ui.setupUi(self)
        self.ui.plot.setLabel('bottom', 'Frequency (MHz)')
        self.ui.plot.setLabel('left', 'Amplitude')
        self.ui.plot.showGrid(x=True, y=True, alpha=1.0)
        #self.ui.plot.setRange(xRange=(0.0, 1600.0))
        self.ui.plot.setBackground('w')
        c = (10, 10, 10)
        self.fftpen = pg.mkPen(color=c)  # add linewidth=0.5, alpha=.5
        self.fftline = self.ui.plot.plot(pen=self.fftpen, name="fft_plot")
        self.fftlastTime = time.time() - 10
        self.fftyrange = 1

# Define main window class from template
WindowTemplate, TemplateBaseClass = loadUiType("HaasoscopePro.ui")
class MainWindow(TemplateBaseClass):

    expect_samples = 100
    samplerate = 3.2  # freq in GHz
    nsunits = 1
    num_board = len(usbs)
    num_logic_inputs = 0
    tenx = 1
    debug = False
    dopattern = False
    debugprint = True
    showbinarydata = True
    debugstrobe = False
    dofast = False
    dooverlapped = False
    dotwochannel = False
    if dotwochannel: num_chan_per_board = 2
    else: num_chan_per_board = 1
    dointerleaved = False
    dooverrange = False
    total_rx_len = 0
    time_start = time.time()
    triggertype = 1  # 0 no trigger, 1 threshold trigger rising, 2 threshold trigger falling, ...
    if dopattern: triggertype = 0
    selectedchannel = 0
    activeusb = usbs[0]
    activeboard = 0
    activexychannel = 0
    tad = 0
    toff = 0
    themuxoutV = True
    phasecs = []
    for ph in range(len(usbs)): phasecs.append([[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]])
    doexttrig = [0] * num_board
    paused = True # will unpause with dostartstop at startup
    downsample = 0
    downsamplefactor = 1
    highresval = 1
    xscale = 1
    xscaling = 1
    yscale = 530 / 1400  # mV/count on 50 Ohm
    min_y = -pow(2, 11) * yscale
    max_y = pow(2, 11) * yscale
    min_x = 0
    max_x = 4 * 10 * expect_samples * downsamplefactor / nsunits / samplerate
    triggerlevel = 127
    triggerdelta = 1
    triggerpos = int(expect_samples * 128 / 256)
    triggertimethresh = 0
    triggerchan = 0
    hline = 0
    vline = 0
    oldtriggertype = 0
    getone = False
    exttriggainscaling = 1.0
    downsamplemerging = 1
    units = "ns"
    dodrawing = True
    chtext = ""
    linepens = []
    nlines = 0
    statuscounter = 0
    nevents = 0
    oldnevents = 0
    tinterval = 100.
    oldtime = time.time()
    nbadclkA = 0
    nbadclkB = 0
    nbadclkC = 0
    nbadclkD = 0
    nbadstr = 0
    eventcounter = [0] * num_board
    nsubsamples = 10 * 4 + 8 + 2  # extra 4 for clk+str, and 2 dead beef
    sample_triggered = [0] * num_board
    downsamplemergingcounter = 0
    doeventcounter = False
    if dooverlapped:
        xydata = np.empty([int(num_chan_per_board * num_board), 2, 10 * expect_samples], dtype=float)
    elif dotwochannel:
        xydata = np.empty([int(num_chan_per_board * num_board), 2, 2 * 10 * expect_samples], dtype=float)
    else:
        xydata = np.empty([int(num_chan_per_board * num_board), 2, 4 * 10 * expect_samples], dtype=float)
        xydatainterleaved = np.empty([int(num_chan_per_board * num_board), 2, 2 * 4 * 10 * expect_samples], dtype=float)
    fitwidthfraction = 0.2
    exttrigstd = 0
    exttrigstdavg = 0
    lastrate = 0
    lastsize = 0

    def __init__(self):
        TemplateBaseClass.__init__(self)
        self.ui = WindowTemplate()
        self.ui.setupUi(self)
        self.ui.runButton.clicked.connect(self.dostartstop)
        self.ui.threshold.valueChanged.connect(self.triggerlevelchanged)
        self.ui.thresholdDelta.valueChanged.connect(self.triggerdeltachanged)
        self.ui.thresholdPos.valueChanged.connect(self.triggerposchanged)
        self.ui.rollingButton.clicked.connect(self.rolling)
        self.ui.singleButton.clicked.connect(self.single)
        self.ui.timeslowButton.clicked.connect(self.timeslow)
        self.ui.timefastButton.clicked.connect(self.timefast)
        self.ui.risingedgeCheck.stateChanged.connect(self.risingfalling)
        self.ui.exttrigCheck.stateChanged.connect(self.exttrig)
        self.ui.totBox.valueChanged.connect(self.tot)
        self.ui.boardBox.valueChanged.connect(self.boardchanged)
        self.ui.triggerChanBox.valueChanged.connect(self.triggerchanchanged)
        self.ui.gridCheck.stateChanged.connect(self.grid)
        self.ui.markerCheck.stateChanged.connect(self.marker)
        self.ui.highresCheck.stateChanged.connect(self.highres)
        self.ui.pllresetButton.clicked.connect(self.pllreset)
        self.ui.adfresetButton.clicked.connect(self.adfreset)
        self.ui.upposButton0.clicked.connect(self.uppos)
        self.ui.downposButton0.clicked.connect(self.downpos)
        self.ui.upposButton1.clicked.connect(self.uppos1)
        self.ui.downposButton1.clicked.connect(self.downpos1)
        self.ui.upposButton2.clicked.connect(self.uppos2)
        self.ui.downposButton2.clicked.connect(self.downpos2)
        self.ui.upposButton3.clicked.connect(self.uppos3)
        self.ui.downposButton3.clicked.connect(self.downpos3)
        self.ui.upposButton4.clicked.connect(self.uppos4)
        self.ui.downposButton4.clicked.connect(self.downpos4)
        self.ui.chanBox.valueChanged.connect(self.selectchannel)
        self.ui.gainBox.valueChanged.connect(self.changegain)
        self.ui.offsetBox.valueChanged.connect(self.changeoffset)
        self.ui.acdcCheck.stateChanged.connect(self.setacdc)
        self.ui.ohmCheck.stateChanged.connect(self.setohm)
        self.ui.oversampCheck.stateChanged.connect(self.setoversamp)
        self.ui.interleavedCheck.stateChanged.connect(self.interleave)
        self.ui.attCheck.stateChanged.connect(self.setatt)
        self.ui.tenxCheck.stateChanged.connect(self.settenx)
        self.ui.actionOutput_clk_left.triggered.connect(self.actionOutput_clk_left)
        self.ui.chanonCheck.stateChanged.connect(self.chanon)
        self.ui.drawingCheck.clicked.connect(self.drawing)
        self.ui.fwfBox.valueChanged.connect(self.fwf)
        self.ui.tadBox.valueChanged.connect(self.setTAD)
        self.ui.twochanCheck.clicked.connect(self.twochan)
        self.ui.ToffBox.valueChanged.connect(self.setToff)
        self.ui.fftCheck.clicked.connect(self.fft)
        self.dofft = False
        self.db = False
        self.lastTime = time.time()
        self.fps = None
        self.lines = []
        self.otherlines = []
        self.savetofile = False  # save scope data to file
        self.doh5 = False  # use the h5 binary file format
        self.numrecordeventsperfile = 1000  # number of events in each file to record before opening new file
        self.timer = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer.timeout.connect(self.updateplot)
        self.timer2 = QtCore.QTimer()
        # noinspection PyUnresolvedReferences
        self.timer2.timeout.connect(self.drawtext)
        self.ui.statusBar.showMessage("Hello!")
        self.ui.plot.setBackground('w')
        self.show()

    def boardchanged(self):
        self.activeusb = usbs[self.ui.boardBox.value()]
        self.activeboard = self.ui.boardBox.value()
        self.selectchannel()

    def selectchannel(self):
        if self.activeboard%2==0: self.ui.exttrigCheck.setEnabled(False)
        else: self.ui.exttrigCheck.setEnabled(True)
        self.selectedchannel = self.ui.chanBox.value()
        self.activexychannel = self.activeboard*self.num_chan_per_board + self.selectedchannel
        p = self.ui.chanColor.palette()
        col = QColor("red")
        if self.activexychannel==1: col = QColor("green")
        if self.activexychannel==2: col = QColor("blue")
        if self.activexychannel==3: col = QColor("magenta")
        if self.activexychannel>=4: print("Not ready for >2 boards yet!")
        p.setColor(QPalette.Base, col)  # Set background color of box
        self.ui.chanColor.setPalette(p)
        if self.lines[self.activexychannel].isVisible():
            self.ui.chanonCheck.setCheckState(QtCore.Qt.Checked)
        else:
            self.ui.chanonCheck.setCheckState(QtCore.Qt.Unchecked)

    def fft(self):
        if self.ui.fftCheck.checkState() == QtCore.Qt.Checked:
            self.fftui = FFTWindow()
            self.fftui.setWindowTitle('Haasoscope Pro FFT of board '+str(self.activeboard)+' channel ' + str(self.selectedchannel))
            self.fftui.show()
            self.dofft = True
        else:
            self.fftui.close()
            self.dofft = False

    def twochan(self):
        self.dotwochannel = self.ui.twochanCheck.checkState() == QtCore.Qt.Checked
        if dotwochannel[self.activeboard]: self.num_chan_per_board = 2
        else: self.num_chan_per_board = 1

    def changeoffset(self):
        dooffset(self.activeusb, self.selectedchannel, self.ui.offsetBox.value())

    def changegain(self):
        setgain(self.activeusb, self.selectedchannel, self.ui.gainBox.value())

    def fwf(self):
        self.fitwidthfraction = self.ui.fwfBox.value() / 100.
        print("fwf now", self.fitwidthfraction)

    def setTAD(self):
        self.tad = self.ui.tadBox.value()
        spicommand(self.activeusb, "TAD", 0x02, 0xB6, self.tad, False, quiet=True)

    def setToff(self):
        self.toff = self.ui.ToffBox.value()

    def adfreset(self, board):
        if not board: board=self.activeboard # if called by pressing button
        usb = usbs[board]
        # adf4350(150.0, None, 10) # need larger rcounter for low freq
        adf4350(usb, self.samplerate * 1000 / 2, None, themuxout=self.themuxoutV)
        time.sleep(0.1)
        res = boardinbits(usb)
        if not getbit(res, 0): print("Adf pll for board",board,"not locked?")  # should be 1 if locked
        else: print("Adf pll locked for board",board)

    def chanon(self):
        if self.ui.chanonCheck.checkState() == QtCore.Qt.Checked:
            self.lines[self.activexychannel].setVisible(True)
        else:
            self.lines[self.activexychannel].setVisible(False)

    def setacdc(self):
        setchanacdc(self.activeusb, self.selectedchannel,
                    self.ui.acdcCheck.checkState() == QtCore.Qt.Checked)  # will be True for AC, False for DC

    def setohm(self):
        setchanimpedance(self.activeusb, self.selectedchannel,
                         self.ui.ohmCheck.checkState() == QtCore.Qt.Checked)  # will be True for 1M ohm, False for 50 ohm

    def setatt(self):
        setchanatt(self.activeusb, self.selectedchannel,
                   self.ui.attCheck.checkState() == QtCore.Qt.Checked)  # will be True for attenuation on

    def settenx(self):
        if self.ui.tenxCheck.checkState() == QtCore.Qt.Checked:
            self.tenx = 10
        else:
            self.tenx = 1

    def setoversamp(self):
        setsplit(self.activeusb,
                 self.ui.oversampCheck.checkState() == QtCore.Qt.Checked)  # will be True for oversampling, False otherwise

    def interleave(self):
        self.dointerleaved = self.ui.interleavedCheck.checkState() == QtCore.Qt.Checked
        self.timechanged()

    def dophase(self, board, plloutnum, updown, pllnum=None, quiet=False):
        # for 3rd byte, 000:all 001:M 010=2:C0 011=3:C1 100=4:C2 101=5:C3 110=6:C4
        # for 4th byte, 1 is up, 0 is down
        if pllnum is None: pllnum = int(self.ui.pllBox.value())
        usbs[board].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))
        if updown:
            self.phasecs[board][pllnum][plloutnum] = self.phasecs[board][pllnum][plloutnum] + 1
        else:
            self.phasecs[board][pllnum][plloutnum] = self.phasecs[board][pllnum][plloutnum] - 1
        if not quiet: print("phase for pllnum", pllnum, "plloutnum", plloutnum, "on board", board, "now",
                            self.phasecs[board][pllnum][plloutnum])

    def uppos(self):
        self.dophase(self.activeboard, plloutnum=0, updown=1)

    def uppos1(self):
        self.dophase(self.activeboard, plloutnum=1, updown=1)

    def uppos2(self):
        self.dophase(self.activeboard, plloutnum=2, updown=1)

    def uppos3(self):
        self.dophase(self.activeboard, plloutnum=3, updown=1)

    def uppos4(self):
        self.dophase(self.activeboard, plloutnum=4, updown=1)

    def downpos(self):
        self.dophase(self.activeboard, plloutnum=0, updown=0)

    def downpos1(self):
        self.dophase(self.activeboard, plloutnum=1, updown=0)

    def downpos2(self):
        self.dophase(self.activeboard, plloutnum=2, updown=0)

    def downpos3(self):
        self.dophase(self.activeboard, plloutnum=3, updown=0)

    def downpos4(self):
        self.dophase(self.activeboard, plloutnum=4, updown=0)

    def pllreset(self, board):
        if not board: board = self.activeboard # if we called it from the button
        usbs[board].send(bytes([5, 99, 99, 99, 100, 100, 100, 100]))
        tres = usbs[board].recv(4)
        print("pllreset sent to board",board,"- got back:", tres[3], tres[2], tres[1], tres[0])
        self.phasecs[board] = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]  # reset counters
        # adjust phases
        n = 2  # amount to adjust (+ or -)
        for i in range(abs(n)): self.dophase(board, 2, n > 0, pllnum=0, quiet=(i != abs(n) - 1))  # adjust phase of c2, clkout
        n = -1  # amount to adjust (+ or -)
        for i in range(abs(n)): self.dophase(board, 3, n > 0, pllnum=0, quiet=(i != abs(n) - 1))  # adjust phase of c3
        n = 0  # amount to adjust (+ or -)
        for i in range(abs(n)): self.dophase(board, 4, n > 0, pllnum=0, quiet=(i != abs(n) - 1))  # adjust phase of c4

    def wheelEvent(self, event):  # QWheelEvent
        if hasattr(event, "delta"):
            if event.delta() > 0:
                self.uppos()
            else:
                self.downpos()
        elif hasattr(event, "angleDelta"):
            if event.angleDelta() > 0:
                self.uppos()
            else:
                self.downpos()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Up: self.uppos()
        if event.key() == QtCore.Qt.Key_Down: self.downpos()
        if event.key() == QtCore.Qt.Key_Left: self.timefast()
        if event.key() == QtCore.Qt.Key_Right: self.timeslow()
        # modifiers = QtWidgets.QApplication.keyboardModifiers()

    @staticmethod
    def actionOutput_clk_left():
        for board in range(len(usbs)):
            usb = usbs[board]
            clockswitch(usb, board, True)
            clockswitch(usb, board, False)

    def exttrig(self, value):
        board = self.ui.boardBox.value()
        self.doexttrig[board] = value
        print("doexttrig", self.doexttrig[board], "for board", board)

    def grid(self):
        if self.ui.gridCheck.isChecked():
            self.ui.plot.showGrid(x=True, y=True)
        else:
            self.ui.plot.showGrid(x=False, y=False)

    def marker(self):
        if self.ui.markerCheck.isChecked():
            for li in range(self.nlines):
                self.lines[li].setSymbol("o")
                self.lines[li].setSymbolSize(3)
                # self.lines[li].setSymbolPen("black")
                self.lines[li].setSymbolPen(self.linepens[li].color())
                self.lines[li].setSymbolBrush(self.linepens[li].color())
        else:
            for li in range(self.nlines):
                self.lines[li].setSymbol(None)

    def dostartstop(self):
        if self.paused:
            self.timer.start(0)
            self.timer2.start(1000)
            self.paused = False
            self.ui.runButton.setChecked(True)
        else:
            self.timer.stop()
            self.timer2.stop()
            self.paused = True
            self.ui.runButton.setChecked(False)

    def triggerlevelchanged(self, value):
        if value + self.triggerdelta < 256 and value - self.triggerdelta > 0:
            self.triggerlevel = value
            for usb in usbs: self.sendtriggerinfo(usb)
            self.drawtriggerlines()

    def triggerdeltachanged(self, value):
        if value + self.triggerlevel < 256 and self.triggerlevel - value > 0:
            self.triggerdelta = value
            for usb in usbs: self.sendtriggerinfo(usb)

    def triggerposchanged(self, value):
        self.triggerpos = int(self.expect_samples * value / 256)
        for usb in usbs: self.sendtriggerinfo(usb)
        self.drawtriggerlines()

    def triggerchanchanged(self):
        self.triggerchan = self.ui.triggerChanBox.value()
        for usb in usbs: self.sendtriggerinfo(usb)

    def sendtriggerinfo(self, usb):
        usb.send(bytes([8, self.triggerlevel + 1, self.triggerdelta, int(self.triggerpos / 256), self.triggerpos % 256,
                        self.triggertimethresh, self.triggerchan, 100]))
        usb.recv(4)

    def drawtriggerlines(self):
        self.hline = (self.triggerlevel - 127) * self.yscale * 16
        self.otherlines[1].setData([self.min_x, self.max_x],
                                   [self.hline, self.hline])  # horizontal line showing trigger threshold
        point = self.triggerpos + 0.0
        if 0 < self.downsample < 10: point = point + 1.0 / pow(2, self.downsamplefactor - 1)
        self.vline = 2 * 10 * point * (self.downsamplefactor / self.nsunits / self.samplerate)
        if not self.dotwochannel: self.vline = self.vline * 2
        self.otherlines[0].setData([self.vline, self.vline], [max(self.hline + self.min_y / 2, self.min_y),
                                                              min(self.hline + self.max_y / 2,
                                                                  self.max_y)])  # vertical line showing trigger time

    def tot(self):
        self.triggertimethresh = self.ui.totBox.value()
        for usb in usbs: self.sendtriggerinfo(usb)

    def rolling(self):
        if self.triggertype > 0:
            self.oldtriggertype = self.triggertype
            self.triggertype = 0
            self.ui.risingedgeCheck.setEnabled(False)
        else:
            self.triggertype = self.oldtriggertype
        if self.triggertype == 1 or self.triggertype == 2: self.ui.risingedgeCheck.setEnabled(True)
        self.ui.rollingButton.setChecked(self.triggertype > 0)
        if self.triggertype > 0:
            self.ui.rollingButton.setText("Normal")
        else:
            self.ui.rollingButton.setText("Auto")

    def single(self):
        self.getone = not self.getone
        self.ui.singleButton.setChecked(self.getone)

    def highres(self, value):
        self.highresval = value > 0
        # print("highres",self.highresval)
        for usb in usbs: self.telldownsample(usb, self.downsample)

    def telldownsample(self, usb, ds):
        if ds < 0: ds = 0
        if ds == 0:
            ds = 0
            self.downsamplemerging = 1
        if ds == 1:
            ds = 0
            self.downsamplemerging = 2
        if ds == 2:
            ds = 0
            self.downsamplemerging = 4
        if ds == 3:
            ds = 0
            if not self.dotwochannel:
                self.downsamplemerging = 8
            else:
                self.downsamplemerging = 10
        if ds == 4:
            ds = 0
            self.downsamplemerging = 20
        if not self.dotwochannel:
            if ds == 5:
                ds = 0
                self.downsamplemerging = 40
            if ds > 5:
                ds = ds - 5
                self.downsamplemerging = 40
        else:
            if ds > 4:
                ds = ds - 4
                self.downsamplemerging = 20
        self.downsamplefactor = self.downsamplemerging * pow(2, ds)
        # print("ds, dsm, dsf",ds,self.downsamplemerging,self.downsamplefactor)
        usb.send(bytes([9, ds, self.highresval, self.downsamplemerging, 100, 100, 100, 100]))
        usb.recv(4)

    def timefast(self):
        amount = 1
        modifiers = app.keyboardModifiers()
        if modifiers == QtCore.Qt.ShiftModifier:
            amount *= 5
        if (self.downsample - amount) < 0:
            print("downsample too small!")
            return
        self.downsample = self.downsample - amount
        for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()

    def timeslow(self):
        if self.dooverlapped:
            print("downsampling not supported in overlap mode")
            return
        amount = 1
        modifiers = app.keyboardModifiers()
        if modifiers == QtCore.Qt.ShiftModifier:
            amount *= 5
        if (self.downsample + amount - 5) > 31:
            print("downsample too large!")
            return
        self.downsample = self.downsample + amount
        for usb in usbs: self.telldownsample(usb, self.downsample)
        self.timechanged()

    def timechanged(self):
        self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
        baremaxx = 4 * 10 * self.expect_samples * self.downsamplefactor / self.samplerate
        if baremaxx > 5:
            self.nsunits = 1
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "ns"
        if baremaxx > 5000:
            self.nsunits = 1000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "us"
        if baremaxx > 5000000:
            self.nsunits = 1000000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "ms"
        if baremaxx > 5000000000:
            self.nsunits = 1000000000
            self.max_x = 4 * 10 * self.expect_samples * (self.downsamplefactor / self.nsunits / self.samplerate)
            self.units = "s"
        self.ui.plot.setLabel('bottom', "Time (" + self.units + ")")
        if self.dooverlapped:
            for c in range(4):
                self.xydata[c][0] = np.array([range(0, 10 * self.expect_samples)]) * (
                            4 * self.downsamplefactor / self.nsunits / self.samplerate)
        elif self.dotwochannel:
            for c in range(self.num_chan_per_board * self.num_board):
                self.xydata[c][0] = np.array([range(0, 2 * 10 * self.expect_samples)]) * (
                            2 * self.downsamplefactor / self.nsunits / self.samplerate)
        else:
            for c in range(self.num_board):
                self.xydata[c][0] = np.array([range(0, 4 * 10 * self.expect_samples)]) * (
                            1 * self.downsamplefactor / self.nsunits / self.samplerate)
                if self.num_board%2==0 and self.dointerleaved:
                    self.xydatainterleaved[int(c/2)][0] = np.array([range(0, 2 * 4 * 10 * self.expect_samples)]) * (
                            0.5 * self.downsamplefactor / self.nsunits / self.samplerate)
        self.ui.plot.setRange(xRange=(self.min_x, self.max_x), padding=0.00)
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        self.drawtriggerlines()
        self.ui.timebaseBox.setText("downsample " + str(self.downsample))

    def risingfalling(self):
        fallingedge = not self.ui.risingedgeCheck.checkState()
        if self.triggertype == 1:
            if fallingedge: self.triggertype = 2
        if self.triggertype == 2:
            if not fallingedge: self.triggertype = 1

    def drawing(self):
        if self.ui.drawingCheck.checkState() == QtCore.Qt.Checked:
            self.dodrawing = True
            # print("drawing now",self.dodrawing)
        else:
            self.dodrawing = False
            # print("drawing now",self.dodrawing)

    def adjustclocks(self, board, nbadclkA, nbadclkB, nbadclkC, nbadclkD):
        if ((
                nbadclkA>self.expect_samples or nbadclkB>self.expect_samples or nbadclkC>self.expect_samples or nbadclkD>self.expect_samples)
                and self.phasecs[board][0][2] < 12):  # adjust phase by 90 deg
            n = 6  # amount to adjust clkout (positive)
            for i in range(n): self.dophase(board, 2, 1, pllnum=0, quiet=(i != n - 1))  # adjust phase of clkout

    def updateplot(self):
        self.mainloop()
        self.statuscounter = self.statuscounter + 1
        now = time.time()
        dt = now - self.lastTime + 0.00001
        self.lastTime = now
        if self.fps is None:
            self.fps = 1.0 / dt
        else:
            s = np.clip(dt * 3., 0, 1)
            self.fps = self.fps * (1 - s) + (1.0 / dt) * s
        if self.statuscounter % 20 == 0: self.ui.statusBar.showMessage("%0.2f fps, %d events, %0.2f Hz, %0.2f MB/s" % (
            self.fps, self.nevents, self.lastrate, self.lastrate * self.lastsize / 1e6))
        if not self.dodrawing: return
        # self.ui.plot.setTitle("%0.2f fps, %d events, %0.2f Hz, %0.2f MB/s"%(self.fps,self.nevents,self.lastrate,self.lastrate*self.lastsize/1e6))
        for li in range(self.nlines):
            if not self.dointerleaved:
                self.lines[li].setData(self.xydata[li][0], self.xydata[li][1])
            else:
                if li%2==0:
                    self.xydatainterleaved[int(li/2)][1][0::2] = self.xydata[li][1]
                    self.xydatainterleaved[int(li/2)][1][1::2] = self.xydata[li+1][1]
                    self.lines[li].setData(self.xydatainterleaved[int(li/2)][0],self.xydatainterleaved[int(li/2)][1])
        if self.dofft and hasattr(self,"fftfreqplot_xdata"):
            self.fftui.fftline.setPen(self.linepens[self.activeboard * self.num_chan_per_board + self.selectedchannel])
            self.fftui.fftline.setData(self.fftfreqplot_xdata,self.fftfreqplot_ydata)
            self.fftui.ui.plot.setTitle('Haasoscope Pro FFT of board '+str(self.activeboard)+' channel ' + str(self.selectedchannel))
            self.fftui.ui.plot.setLabel('bottom', self.fftax_xlabel)
            self.fftui.ui.plot.setRange(xRange=(0.0, self.fftax_xlim))
            now = time.time()
            dt = now - self.fftui.fftlastTime
            if dt>3.0 or self.fftyrange<self.fftfreqplot_ydatamax*1.1:
                self.fftui.fftlastTime = now
                self.fftui.ui.plot.setRange(yRange=(0.0, self.fftfreqplot_ydatamax*1.1))
                self.fftyrange = self.fftfreqplot_ydatamax * 1.1
            if not self.fftui.isVisible(): # closed the fft window
                self.dofft = False
                self.ui.fftCheck.setCheckState(QtCore.Qt.Unchecked)
        app.processEvents()

    def getchannels(self, board):
        tt = self.triggertype
        if self.doexttrig[board] > 0: tt = 3
        usbs[board].send(bytes([1, tt, self.dotwochannel, 99] + inttobytes(
            self.expect_samples - self.triggerpos + 1)))  # length to take after trigger (last 4 bytes)
        triggercounter = usbs[board].recv(4)  # get the 4 bytes
        acqstate = triggercounter[0]
        if acqstate == 251:  # an event is ready to be read out
            #print("board",board,"sample triggered", binprint(triggercounter[3]), binprint(triggercounter[2]), binprint(triggercounter[1]))
            gotzerobit = False
            for s in range(21):
                thebit = getbit(triggercounter[int(s / 8) + 1], s % 8)
                if thebit == 0: gotzerobit = True
                if thebit == 1 and gotzerobit:
                    self.sample_triggered[board] = s
                    gotzerobit = False
            #if self.sample_triggered[board]<10: self.sample_triggered[board] += 0
            #print("sample_triggered", self.sample_triggered[board], "for board", board)
            return 1
        else:
            return 0

    def getpredata(self, board):
        if self.doeventcounter:
            usbs[board].send(bytes([2, 3, 100, 100, 100, 100, 100, 100]))  # get eventcounter
            res = usbs[board].recv(4)
            eventcountertemp = res[0] + 256 * res[1] + 256 * 256 * res[2] + 256 * 256 * 256 * res[3]
            if eventcountertemp != self.eventcounter[board] + 1 and eventcountertemp != 0:  # check event count, but account for rollover
                print("Event counter not incremented by 1?", eventcountertemp, self.eventcounter[board], " for board", board)
            self.eventcounter[board] = eventcountertemp
        downsamplemergingcounter = 0
        if self.downsamplemerging > 1:
            usbs[board].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))  # get downsamplemergingcounter
            res = usbs[board].recv(4)
            downsamplemergingcounter = res[0]
            if downsamplemergingcounter == self.downsamplemerging:
                if not self.doexttrig[board]:
                    downsamplemergingcounter = 0
            # print("downsamplemergingcounter", downsamplemergingcounter)
        return downsamplemergingcounter

    def getdata(self, usb):
        expect_len = self.expect_samples * 2 * self.nsubsamples  # length to request: each adc bit is stored as 10 bits in 2 bytes
        usb.send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))  # send the 4 bytes to usb
        data = usb.recv(expect_len)  # recv from usb
        rx_len = len(data)
        self.total_rx_len += rx_len
        if expect_len != rx_len:
            print('*** expect_len (%d) and rx_len (%d) mismatch' % (expect_len, rx_len))
        if self.debug:
            time.sleep(.5)
            # oldbytes()
        return data

    def drawchannels(self, data, board, downsamplemergingcounter):
        if self.dofast: return
        if self.doexttrig[board]:
            if board % 2 == 1: boardtouse = board-1
            else: boardtouse = board+1
            self.sample_triggered[board] = self.sample_triggered[boardtouse] # take from the other board when interleaving using ext trig
        nbadclkA = 0
        nbadclkB = 0
        nbadclkC = 0
        nbadclkD = 0
        self.nbadstr = 0
        for s in range(0, self.expect_samples):
            chan = -1
            for n in range(self.nsubsamples):  # the subsample to get
                pbyte = self.nsubsamples * 2 * s + 2 * n
                lowbits = data[pbyte + 0]
                highbits = data[pbyte + 1]
                if n < 40 and getbit(highbits, 3):
                    highbits = (highbits - 16) * 256
                else:
                    highbits = highbits * 256
                val = highbits + lowbits
                if n % 10 == 0: chan = chan + 1

                if n == 40 and val & 0x5555 != 4369 and val & 0x5555 != 17476:
                    nbadclkA = nbadclkA + 1
                if n == 41 and val & 0x5555 != 1 and val & 0x5555 != 4:
                    nbadclkA = nbadclkA + 1
                if n == 42 and val & 0x5555 != 4369 and val & 0x5555 != 17476:
                    nbadclkB = nbadclkB + 1
                if n == 43 and val & 0x5555 != 1 and val & 0x5555 != 4:
                    nbadclkB = nbadclkB + 1
                if n == 44 and val & 0x5555 != 4369 and val & 0x5555 != 17476:
                    nbadclkC = nbadclkC + 1
                if n == 45 and val & 0x5555 != 1 and val & 0x5555 != 4:
                    nbadclkC = nbadclkC + 1
                if n == 46 and val & 0x5555 != 4369 and val & 0x5555 != 17476:
                    nbadclkD = nbadclkD + 1
                if n == 47 and val & 0x5555 != 1 and val & 0x5555 != 4:
                    nbadclkD = nbadclkD + 1
                # if 40<=n<48 and nbadclkD:
                #    print("s=", s, "n=", n, "pbyte=", pbyte, "chan=", chan, binprint(data[pbyte + 1]), binprint(data[pbyte + 0]), val)

                if 40 <= n < 48:
                    strobe = val & 0xaaaa
                    if strobe != 0:
                        if strobe != 8 and strobe != 128 and strobe != 2048 and strobe != 32768:
                            if strobe * 4 != 8 and strobe * 4 != 128 and strobe * 4 != 2048 and strobe * 4 != 32768:
                                if self.debugstrobe: print("s=", s, "n=", n, "str", binprint(strobe), strobe)
                                self.nbadstr = self.nbadstr + 1

                if self.debug and self.debugprint:
                    goodval = -1
                    if s < 0 or (n < 40 and val != 0 and val != goodval):
                        if self.showbinarydata and n < 40:
                            # if s<0 or chan!=3 or (chan==3 and val!=255 and val!=511 and val!=1023 and val!=2047):
                            if s < 100:
                                if lowbits > 0 or highbits > 0:
                                    print("s=", s, "n=", n, "pbyte=", pbyte, "chan=", chan, binprint(data[pbyte + 1]),
                                          binprint(data[pbyte + 0]), val)
                        elif n < 40:
                            print("s=", s, "n=", n, "pbyte=", pbyte, "chan=", chan, hex(data[pbyte + 1]),
                                  hex(data[pbyte + 0]))
                if n < 40:
                    # val = -val # if we're swapping inputs
                    val = val * self.yscale * self.tenx
                    shiftmax = 1
                    if self.downsamplemerging == 1:
                        samp = s * 10 + (9 - (n % 10))  # bits come out last to first in lvds receiver group of 10
                        if s < (self.expect_samples - shiftmax): samp = samp - self.sample_triggered[board]
                        if self.dooverlapped:
                            self.xydata[chan][1][samp] = val
                        elif self.dotwochannel:
                            if chan % 2 == 0:
                                chani = int(chan / 2)
                            else:
                                chani = int((chan - 1) / 2)
                            if not self.doexttrig[board]:
                                self.xydata[board*self.num_chan_per_board + chan%2][1][chani+ 2*samp] = val
                            else:
                                self.xydata[board*self.num_chan_per_board + chan%2][1][ (chani+ 2*samp+ self.toff) % (20*self.expect_samples) ] = val
                        else:
                            if not self.doexttrig[board]:
                                self.xydata[board][1][chan + 4 * samp] = val
                            else:
                                self.xydata[board][1][(chan + 4 * samp + self.toff) % (40 * self.expect_samples)] = val * self.exttriggainscaling
                    else:
                        if self.dotwochannel:
                            samp = s * 20 + chan * 10 + 9 - n
                            if n < 20: samp = samp + 10
                            if s < (self.expect_samples - shiftmax): samp = samp - int(2 * (self.sample_triggered[board] + (downsamplemergingcounter-1)%self.downsamplemerging * 10) / self.downsamplemerging)
                            if not self.doexttrig[board]:
                                self.xydata[board * self.num_chan_per_board + chan % 2][1][samp] = val
                            else:
                                self.xydata[board * self.num_chan_per_board + chan % 2][1][(samp + self.toff) % (20 * self.expect_samples)] = val
                        else:
                            samp = s * 40 + 39 - n
                            if s < (self.expect_samples - shiftmax): samp = samp - int(4 * (self.sample_triggered[board] + (downsamplemergingcounter-1)%self.downsamplemerging * 10) / self.downsamplemerging)
                            if not self.doexttrig[board]:
                                self.xydata[board][1][samp] = val
                            else:
                                self.xydata[board][1][(samp + self.toff) % (40 * self.expect_samples)] = val
        self.adjustclocks(board, nbadclkA, nbadclkB, nbadclkC, nbadclkD)
        if board == self.activeboard:
            self.nbadclkA = nbadclkA
            self.nbadclkB = nbadclkB
            self.nbadclkC = nbadclkC
            self.nbadclkD = nbadclkD

    def drawtext(self):  # happens once per second
        thestr = "Nbadclks A B C D " + str(self.nbadclkA) + " " + str(self.nbadclkB) + " " + str(
            self.nbadclkC) + " " + str(self.nbadclkD)
        thestr += "\n" + "Nbadstrobes " + str(self.nbadstr)
        thestr += "\n" + gettemps(self.activeusb)
        thestr += "\n" + "Trigger threshold " + str(round(self.hline, 3))
        thestr += "\n" + "Mean " + str(np.mean(self.xydata[self.activexychannel][1]).round(2))
        thestr += "\n" + "RMS " + str(np.std(self.xydata[self.activexychannel][1]).round(2))

        if not self.dooverlapped:
            if not self.dointerleaved:
                targety = self.xydata[self.activexychannel]
            else:
                targety = self.xydatainterleaved[int(self.activeboard/2)]
            p0 = [max(targety[1]), self.vline - 10, 20, min(targety[1])]  # this is an initial guess
            fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
            xc = targety[0][(targety[0] > self.vline - fitwidth) & (
                        targety[0] < self.vline + fitwidth)]  # only fit in range
            yc = targety[1][
                (targety[0] > self.vline - fitwidth) & (targety[0] < self.vline + fitwidth)]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                popt, pcov = curve_fit(fit_rise, xc, yc, p0)
                perr = np.sqrt(np.diag(pcov))
            risetime = 0.8 * 0.7 * popt[2] # calibrated
            risetimeerr = perr[2]
            # print(popt)
            thestr += "\n" + "Rise time " + str(risetime.round(2)) + "+-" + str(risetimeerr.round(2)) + " " + self.units

            if not self.dotwochannel and self.doexttrig[self.activeboard] and self.num_board>1:
                if self.activeboard % 2 == 1: c1 = self.activeboard-1
                else: c1 = self.activeboard+1
                thestr += "\n" + "RMS of board "+str(c1)+" vs board "+str(self.activeboard)+": " + str(round(self.exttrigstdavg,2))

        self.ui.textBrowser.setText(thestr)

    def calculatethings(self):
        if self.activeboard % 2 == 1:
            c1 = self.activeboard - 1
        else:
            c1 = self.activeboard + 1 # other board we are merging with
        c = self.activeboard # the exttrig board
        fitwidth = (self.max_x - self.min_x) * self.fitwidthfraction
        yc = self.xydata[c][1][
            (self.xydata[c][0] > self.vline - fitwidth) & (self.xydata[c][0] < self.vline + fitwidth)]
        yc1 = self.xydata[c1][1][
            (self.xydata[c1][0] > self.vline - fitwidth) & (self.xydata[c1][0] < self.vline + fitwidth)]
        self.exttrigstd = self.exttrigstd + np.std(yc1 - yc)
        extrigboardmean = np.mean(yc)
        otherboardmean = np.mean(yc1)
        self.xydata[c1][1] += extrigboardmean - otherboardmean
        extrigboardstd = np.std(yc)
        otherboardstd = np.std(yc1)
        self.xydata[c1][1] *= extrigboardstd/otherboardstd

    def plot_fft(self):
        y = self.xydata[self.activeboard * self.num_chan_per_board + self.selectedchannel][1]  # channel signal to take fft of
        n = len(y)  # length of the signal
        k = np.arange(n)
        uspersample = self.downsamplefactor / self.samplerate / 1000.
        # t = np.arange(0,1,1.0/n) * (n*uspersample) # time vector in us
        frq = (k / uspersample)[list(range(int(n / 2)))] / n  # one side frequency range up to Nyquist
        Y = np.fft.fft(y)[list(range(int(n / 2)))] / n  # fft computing and normalization
        Y[0] = 0  # to suppress DC
        if np.max(frq) < .001:
            self.fftfreqplot_xdata = frq * 1000000.0
            self.fftax_xlabel = 'Frequency (Hz)'
            self.fftax_xlim = 1000000.0 * frq[int(n / 2) - 1]
        elif np.max(frq) < 1.0:
            self.fftfreqplot_xdata = frq * 1000.0
            self.fftax_xlabel = 'Frequency (kHz)'
            self.fftax_xlim = 1000.0 * frq[int(n / 2) - 1]
        else:
            self.fftfreqplot_xdata = frq
            self.fftax_xlabel = 'Frequency (MHz)'
            self.fftax_xlim = frq[int(n / 2) - 1]
        self.fftfreqplot_ydata = abs(Y)
        self.fftfreqplot_ydatamax = np.max(abs(Y))

    def fastadclineclick(self, curve):
        for li in range(self.nlines):
            if curve is self.lines[li].curve:
                # print "selected curve", li
                self.ui.chanBox.setValue(li % self.num_chan_per_board)
                self.ui.boardBox.setValue(int(li / self.num_chan_per_board))
                modifiers = app.keyboardModifiers()
                if modifiers == QtCore.Qt.ShiftModifier:
                    self.ui.trigchanonCheck.toggle()
                elif modifiers == QtCore.Qt.ControlModifier:
                    self.ui.chanonCheck.toggle()

    def launch(self):
        self.nlines = self.num_chan_per_board * self.num_board
        chan=0
        for board in range(self.num_board):
            for boardchan in range(self.num_chan_per_board):
                print("chan=",chan, " board=",board, "boardchan=",boardchan)
                c = (0, 0, 0)
                if chan == 0: c = QColor("red")
                if chan == 1: c = QColor("green")
                if chan == 2: c = QColor("blue")
                if chan == 3: c = QColor("magenta")
                pen = pg.mkPen(color=c)  # add linewidth=1.0, alpha=.9
                line = self.ui.plot.plot(pen=pen, name=self.chtext + str(chan))
                line.curve.setClickable(True)
                line.curve.sigClicked.connect(self.fastadclineclick)
                self.lines.append(line)
                self.linepens.append(pen)
                chan += 1

            r1 = 0
            g1 = 2
            b1 = 0
            r2 = 1
            g2 = 0
            b2 = 1
            send_leds(usbs[board], r1, g1, b1, r2, g2, b2)

        self.ui.chanBox.setMaximum(self.num_chan_per_board - 1)
        self.ui.boardBox.setMaximum(self.num_board - 1)

        # trigger lines
        self.vline = 0.0
        pen = pg.mkPen(color="k", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([self.vline, self.vline], [-2.0, 2.0], pen=pen, name="trigger time vert")
        self.otherlines.append(line)

        self.hline = 0.0
        pen = pg.mkPen(color="k", width=1.0, style=QtCore.Qt.DashLine)
        line = self.ui.plot.plot([-2.0, 2.0], [self.hline, self.hline], pen=pen, name="trigger thresh horiz")
        self.otherlines.append(line)

        # other stuff
        self.ui.plot.setLabel('bottom', "Time (ns)")
        self.ui.plot.setLabel('left', "Voltage (mV)")
        self.ui.plot.setRange(yRange=(self.min_y, self.max_y), padding=0.01)
        for usb in usbs: self.telldownsample(usb, 0)
        self.timechanged()
        self.ui.plot.showGrid(x=True, y=True)

    def setup_connections(self, board):
        print("Setting up board",board)
        #version(usbs[board])
        self.adfreset(board)
        self.pllreset(board)
        board_setup(usbs[board], self.dopattern, self.dotwochannel, self.dooverrange)
        for c in range(2): setchanacdc(usbs[board], c, 0)
        self.sendtriggerinfo(usbs[board])
        return 1

    def init(self):
        self.tot()
        self.launch()
        self.selectchannel()
        self.timechanged()
        self.dostartstop()
        return 1

    def mainloop(self):
        if self.paused:
            time.sleep(.1)
        else:
            rx_len = 0
            try:
                readyevent = [0]*self.num_board
                for board in reversed(range(self.num_board)): # go backwards through the boards to get the triggerinfo for the right events
                    readyevent[board] = self.getchannels(board)
                for board in range(self.num_board):
                    if not readyevent[board]: continue
                    downsamplemergingcounter = self.getpredata(board)
                    data = self.getdata(usbs[board])
                    rx_len = rx_len + len(data)
                    if self.dofft and board==self.activeboard: self.plot_fft()
                    self.drawchannels(data, board, downsamplemergingcounter)
                if not self.dotwochannel and self.doexttrig[self.activeboard] and self.num_board>1:
                    self.calculatethings()
                if self.getone and rx_len > 0:
                    self.dostartstop()
                    self.drawtext()
            except ftd2xx.DeviceError:
                print("Device error")
                sys.exit(1)
            if self.db: print(time.time() - self.oldtime, "done with evt", self.nevents)
            if rx_len > 0: self.nevents += 1
            if self.nevents - self.oldnevents >= self.tinterval:

                self.exttrigstdavg = self.exttrigstd / self.tinterval
                self.exttrigstd =0

                now = time.time()
                elapsedtime = now - self.oldtime
                self.oldtime = now
                self.lastrate = round(self.tinterval / elapsedtime, 2)
                self.lastsize = rx_len
                if not self.dodrawing: print(self.nevents, "events,", self.lastrate, "Hz",
                                             round(self.lastrate * self.lastsize / 1e6, 3), "MB/s")
                self.oldnevents = self.nevents

    def closeEvent(self, event):
        print("Handling closeEvent", event)
        self.timer.stop()
        self.timer2.stop()
        if hasattr(self,"fftui"): self.fftui.close()
        for usb in usbs: cleanup(usb)

if __name__ == '__main__':
    print('Argument List:', str(sys.argv))
    for a in sys.argv:
        if a[0] == "-":
            print(a)
    print("Python version", sys.version)
    app = QtWidgets.QApplication.instance()
    standalone = app is None
    if standalone:
        app = QtWidgets.QApplication(sys.argv)
    try:
        font = app.font()
        font.setPixelSize(11)
        app.setFont(font)
        win = MainWindow()
        win.setWindowTitle('Haasoscope Pro Qt')
        for usbi in range(len(usbs)):
            if not win.setup_connections(usbi):
                print("Exiting now - failed setup_connections!")
                cleanup(usbs[usbi])
                sys.exit(1)
        if not win.init():
            print("Exiting now - failed init!")
            for usbi in usbs: cleanup(usbi)
            sys.exit(2)
    except ftd2xx.DeviceError:
        print("Device com failed!")
    if standalone:
        rv = app.exec_()
        sys.exit(rv)
    else:
        print("Done, but Qt window still active!")
