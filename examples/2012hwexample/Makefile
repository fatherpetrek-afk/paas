# Compiler and flags
CXX = g++
CXXFLAGS = -g -MMD -MP -Wall -Wextra -Werror=vla -std=c++11 #-fsanitize=leak,address,undefined # Uncomment sanitizer if applicable

# Executable name
TARGET = partnerMatcher

# Source files
SRCS = PublicTests.cpp Course.cpp CourseOffering.cpp PartnerMatcher.cpp Student.cpp
DEPS = $(SRCS:.cpp=.d)
OBJS = $(SRCS:.cpp=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS)

$(OBJS): Makefile
	$(CXX) $(CXXFLAGS) -c $(@:.o=.cpp) -o $@

-include $(DEPS)

# Clean up
clean:
	rm -f $(DEPS) $(OBJS) $(TARGET)

# Run the program
run: $(TARGET)
	./$(TARGET)

.PHONY: all clean run
