The Methods of a Character

__init__()
    - initialize the object
    - override to add special functions
    - always call super

# Derived from Monoreceiver
attach(controller)
    - attach to a controller
    - generally don't need to override

detach()
    - detach from a controller
    - generally don't need to override

update()
    - periodically called function
    - handles incoming commands from controller
    - override to add more functionality (just be sure to call super())

# Core Functions
set_location(location)
    - set the location of a character, calling all necessary functions

set_name(name)
    - set name for character, checking that it is a unique name

player_set_name(name)
    - calls set_name(), while also checking restrictions enforced on player
    - override to add more restrictions/caps, be sure to call super() method
    - example use: rock names might be in ALL CAPS, cat names might be converted to a cat language, etc.

message(msg)

# Default Character Commands

help
    - sends help menu to the controller
    - generated dynamically as the class gets built
    - type `help` [command] for docstring

look
    - sends a description of the current location
    - lists exits

say
    - message all players in current location 

go
    - go to [exit_name]