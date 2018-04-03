import gaugette.ssd1306
import gaugette.platform
import gaugette.gpio
import time
import sys
import RPi.GPIO as GPIO
import json
from dotstar import Adafruit_DotStar
import threading
GPIO.setmode(GPIO.BCM)

drink_list = [
	{
		"name": "Rum & Coke",
		"ingredients": {
			"rum": 50,
			"coke": 150
		}
	}, {
		"name": "Gin & Tonic",
		"ingredients": {
			"gin": 50,
			"tonic": 150
		}
	}
]

drink_options = [
	{"name": "Gin", "value": "gin"},
	{"name": "Vodka", "value": "vodka"},
	{"name": "Tonic Water", "value": "tonic"}
]

flow_rate = 60.0/100.0

class MenuItem(object):
	def __init__(self, type, name, attributes = None, visible = True):
		self.type = type
		self.name = name
		self.attributes = attributes
		self.visible = visible

class Back(MenuItem):
	def __init__(self, name):
		MenuItem.__init__(self, "back", name)

class Menu(MenuItem):
	def __init__(self, name, attributes = None, visible = True):
		MenuItem.__init__(self, "menu", name, attributes, visible)
		self.options = []
		self.selectedOption = 0
		self.parent = None

	def addOptions(self, options):
		self.options = self.options + options
		self.selectedOption = 0

	def addOption(self, option):
		self.options.append(option)
		self.selectedOption = 0

	def setParent(self, parent):
		self.parent = parent

	def nextSelection(self):
		self.selectedOption = (self.selectedOption + 1) % len(self.options)

	def getSelection(self):
		return self.options[self.selectedOption]

class MenuContext(object):
	def __init__(self, menu, delegate):
		self.topLevelMenu = menu
		self.currentMenu = menu
		self.delegate = delegate
		self.showMenu()

	def showMenu(self):
		"""
		Shows the first selection of the current menu 
		"""
		self.display(self.currentMenu.getSelection());

	def setMenu(self, menu):
		"""
		Sets a new menu to the menu context.

		raises ValueError if the menu has no options
		"""
		if (len(menu.options) == 0):
			raise ValueError("Cannot setMenu on a menu with no options")
		self.topLevelMenu = menu
		self.currentMenu = menu
		self.showMenu();

	def display(self, menuItem):
		"""
		Tells the delegate to display the selection. Advances to the next selection if the 
		menuItem is visible==False
		"""
		self.delegate.prepareForRender(self.topLevelMenu)
		if (not menuItem.visible):
			self.advance()
		else:
			self.delegate.displayMenuItem(menuItem)

	def advance(self):
		"""
		Advances the displayed menu to the next visible option

		raises ValueError if all options are visible==False
		"""
		for i in self.currentMenu.options:
			self.currentMenu.nextSelection()
			selection = self.currentMenu.getSelection()
			if (selection.visible): 
				self.display(selection)
				return
		raise ValueError("At least one option in a menu must be visible!")

	def select(self):
		"""
		Selects the current menu option. Calls menuItemClicked first. If it returns false,
		it uses the default logic. If true, it calls display with the current selection

		defaults:
			"menu" -> sets submenu as the current menu
			"back" -> sets parent menu as the current menu

		returns True if the default logic should be overridden

		throws ValueError if navigating back on a top-level menu

		"""
		selection = self.currentMenu.getSelection()
		if (not self.delegate.menuItemClicked(selection)):
			if (selection.type is "menu"):
				self.setMenu(selection)
			elif (selection.type is "back"):
				if (not self.currentMenu.parent):
					raise ValueError("Cannot navigate back when parent is None")
				self.setMenu(self.currentMenu.parent)
		else:
			self.display(self.currentMenu.getSelection())

class MenuDelegate(object):
	def prepareForRender(self, menu): 
		"""
		Called before the menu needs to display. Useful for changing visibility. 
		"""
		raise NotImplementedError

	def menuItemClicked(self, menuItem):
		"""
		Called when a menu item is selected. Useful for taking action on a menu item click.
		"""
		raise NotImplementedError

	def displayMenuItem(self, menuItem):
		"""
		Called when the menu item should be displayed.
		"""
		raise NotImplementedError

class Bartender(MenuDelegate): 
	def __init__(self):
		# load the pump configuration from file
		self.pump_configuration = Bartender.readPumpConfiguration()
		for pump in self.pump_configuration.keys():
			GPIO.setup(self.pump_configuration[pump]["pin"], GPIO.OUT, initial=GPIO.HIGH)

		# set the oled screen height
		self.screen_width = 128
		self.screen_height = 64

		self.btn1Pin = 13
		self.btn2Pin = 5
	 
	 	# configure interrups for buttons
	 	GPIO.setup(self.btn1Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
		GPIO.setup(self.btn2Pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)  

		# Define which GPIO pins the reset (RST) and DC signals on the OLED display are connected to on the
		# Raspberry Pi. The defined pin numbers must use the WiringPi pin numbering scheme.
		RESET_PIN = 15 # WiringPi pin 15 is GPIO14.
		DC_PIN = 16 # WiringPi pin 16 is GPIO15.

		spi_bus = 0
		spi_device = 0
		gpio = gaugette.gpio.GPIO()
		spi = gaugette.spi.SPI(spi_bus, spi_device)

		# Very important... This lets py-gaugette 'know' what pins to use in order to reset the display
		self.led = gaugette.ssd1306.SSD1306(gpio, spi, reset_pin=RESET_PIN, dc_pin=DC_PIN, rows=self.screen_height, cols=self.screen_width) # Change rows & cols values depending on your display dimensions.
		self.led.begin()
		self.led.clear_display()
		self.led.display()
		self.led.invert_display()
		time.sleep(0.5)
		self.led.normal_display()
		time.sleep(0.5)

		# setup pixels:
		self.numpixels = 45 # Number of LEDs in strip

		# Here's how to control the strip from any two GPIO pins:
		datapin  = 26
		clockpin = 6
		self.strip    = Adafruit_DotStar(self.numpixels, datapin, clockpin)
		self.strip.begin()           # Initialize pins for output
		self.strip.setBrightness(64) # Limit brightness to ~1/4 duty cycle

		# turn everything off
		for i in range(0, self.numpixels):
			self.strip.setPixelColor(i, 0)
		self.strip.show() 

	@staticmethod
	def readPumpConfiguration():
		return json.load(open('pump_config.json'))

	@staticmethod
	def writePumpConfiguration(configuration):
		with open("pump_config.json", "w") as jsonFile:
			json.dump(configuration, jsonFile)

	def startInterrupts(self):
		GPIO.add_event_detect(self.btn1Pin, GPIO.FALLING, callback=self.left_btn, bouncetime=1000)  
		GPIO.add_event_detect(self.btn2Pin, GPIO.FALLING, callback=self.right_btn, bouncetime=2000)  

	def stopInterrupts(self):
		GPIO.remove_event_detect(self.btn1Pin)
		GPIO.remove_event_detect(self.btn2Pin)

	def buildMenu(self, drink_list, drink_options):
		# create a new main menu
		m = Menu("Main Menu")

		# add drink options
		drink_opts = []
		for d in drink_list:
			drink_opts.append(MenuItem('drink', d["name"], {"ingredients": d["ingredients"]}))

		configuration_menu = Menu("Configure")

		# add pump configuration options
		pump_opts = []
		for p in sorted(self.pump_configuration.keys()):
			config = Menu(self.pump_configuration[p]["name"])
			# add fluid options for each pump
			for opt in drink_options:
				# star the selected option
				selected = "*" if opt["value"] == self.pump_configuration[p]["value"] else ""
				config.addOption(MenuItem('pump_selection', opt["name"], {"key": p, "value": opt["value"], "name": opt["name"]}))
			# add a back button so the user can return without modifying
			config.addOption(Back("Back"))
			config.setParent(configuration_menu)
			pump_opts.append(config)

		# add pump menus to the configuration menu
		configuration_menu.addOptions(pump_opts)
		# add a back button to the configuration menu
		configuration_menu.addOption(Back("Back"))
		configuration_menu.setParent(m)

		m.addOptions(drink_opts)
		m.addOption(configuration_menu)
		# create a menu context
		self.menuContext = MenuContext(m, self)

	def filterDrinks(self, menu):
		"""
		Removes any drinks that can't be handled by the pump configuration
		"""
		for i in menu.options:
			if (i.type == "drink"):
				i.visible = False
				ingredients = i.attributes["ingredients"]
				presentIng = 0
				for ing in ingredients.keys():
					for p in self.pump_configuration.keys():
						if (ing == self.pump_configuration[p]["value"]):
							presentIng += 1
				if (presentIng == len(ingredients.keys())): 
					i.visible = True
			elif (i.type == "menu"):
				self.filterDrinks(i)

	def selectConfigurations(self, menu):
		"""
		Adds a selection star to the pump configuration option
		"""
		for i in menu.options:
			if (i.type == "pump_selection"):
				key = i.attributes["key"]
				if (self.pump_configuration[key]["value"] == i.attributes["value"]):
					i.name = "%s %s" % (i.attributes["name"], "*")
				else:
					i.name = i.attributes["name"]
			elif (i.type == "menu"):
				self.selectConfigurations(i)

	def prepareForRender(self, menu):
		self.filterDrinks(menu)
		self.selectConfigurations(menu)
		return True

	def menuItemClicked(self, menuItem):
		if (menuItem.type == "drink"):
			self.makeDrink(menuItem.name, menuItem.attributes["ingredients"])
			return True
		elif(menuItem.type == "pump_selection"):
			self.pump_configuration[menuItem.attributes["key"]]["value"] = menuItem.attributes["value"]
			Bartender.writePumpConfiguration(self.pump_configuration)
			return True
		return False

	def displayMenuItem(self, menuItem):
		self.led.clear_display()
		self.led.draw_text2(0,20,menuItem.name,2)
		self.led.display()

	def cycleLights(self):
		t = threading.currentThread()
		head  = 0               # Index of first 'on' pixel
		tail  = -10             # Index of last 'off' pixel
		color = 0xFF0000        # 'On' color (starts red)

		while getattr(t, "do_run", True):
			self.strip.setPixelColor(head, color) # Turn on 'head' pixel
			self.strip.setPixelColor(tail, 0)     # Turn off 'tail'
			self.strip.show()                     # Refresh strip
			time.sleep(1.0 / 50)             # Pause 20 milliseconds (~50 fps)

			head += 1                        # Advance head position
			if(head >= self.numpixels):           # Off end of strip?
				head    = 0              # Reset to start
				color >>= 8              # Red->green->blue->black
				if(color == 0): color = 0xFF0000 # If black, reset to red

			tail += 1                        # Advance tail position
			if(tail >= self.numpixels): tail = 0  # Off end? Reset

	def lightsEndingSequence(self):
		# make lights green
		for i in range(0, self.numpixels):
			self.strip.setPixelColor(i, 0xFF0000)
		self.strip.show()

		time.sleep(5)

		# turn lights off
		for i in range(0, self.numpixels):
			self.strip.setPixelColor(i, 0)
		self.strip.show() 

	def pour(self, pin, waitTime):
		GPIO.output(pin, GPIO.LOW)
		time.sleep(waitTime)
		GPIO.output(pin, GPIO.HIGH)

	def progressBar(self, waitTime):
		interval = waitTime / 100.0
		for x in range(1, 101):
			self.led.clear_display()
			self.updateProgressBar(x, y=35)
			self.led.display()
			time.sleep(interval)

	def makeDrink(self, drink, ingredients):
		# cancel any button presses while the drink is being made
		self.stopInterrupts()

		# launch a thread to control lighting
		lightsThread = threading.Thread(target=self.cycleLights)
		lightsThread.start()

		# Parse the drink ingredients and spawn threads for pumps
		maxTime = 0
		pumpThreads = []
		for ing in ingredients.keys():
			for pump in self.pump_configuration.keys():
				if ing == self.pump_configuration[pump]["value"]:
					waitTime = ingredients[ing] * flow_rate
					if (waitTime > maxTime):
						maxTime = waitTime
					pump_t = threading.Thread(target=self.pour, args=(self.pump_configuration[pump]["pin"], waitTime))
					pumpThreads.append(pump_t)

		# start the pump threads
		for thread in pumpThreads:
			thread.start()

		# start the progress bar
		self.progressBar(maxTime)

		# wait for threads to finish
		for thread in pumpThreads:
			thread.join()

		# show the main menut
		self.menuContext.showMenu()

		# stop the light thread
		lightsThread.do_run = False
		lightsThread.join()

		# show the ending sequence lights
		self.lightsEndingSequence()

		# reenable interrupts
		self.startInterrupts()

	def left_btn(self, ctx):
		self.menuContext.advance()

	def right_btn(self, ctx):
		self.menuContext.select()

	def updateProgressBar(self, percent, x=15, y=15):
		height = 10
		width = self.screen_width-2*x
		for w in range(0, width):
			self.led.draw_pixel(w + x, y)
			self.led.draw_pixel(w + x, y + height)
		for h in range(0, height):
			self.led.draw_pixel(x, h + y)
			self.led.draw_pixel(self.screen_width-x, h + y)
			for p in range(0, percent):
				p_loc = int(p/100.0*width)
				self.led.draw_pixel(x + p_loc, h + y)

	def run(self):
		self.startInterrupts()
		# main loop
		try:  
			while True:
				time.sleep(0.1)
		  
		except KeyboardInterrupt:  
			GPIO.cleanup()       # clean up GPIO on CTRL+C exit  
		GPIO.cleanup()           # clean up GPIO on normal exit 


bartender = Bartender()
bartender.buildMenu(drink_list, drink_options)
bartender.run()




