#ifndef COURSE_H
#define COURSE_H

#include <string>

#include "CourseOffering.h"
using namespace std;

class CourseOffering;

/**
 * A class representing a Course entry.
 * Each entry should be unique, i.e. one course should be represented by only one Course instance.
 */
class Course {
private:
    /**
     * The title of the course.
     */
    string title;
    /**
     * The course code of the course.
     */
    string courseCode;
    /**
     * The number of credits the course gives when passed.
     */
    int credits;
    /**
     * Number of offerings the course has.
     * This number only refers to offerings that students involved in the PartnerMatcher have taken.
     */
    int numOfferings;
    /**
     * The offerings of this course.
     * The array only contains offerings that students involved in the PartnerMatcher have taken.
     */
    CourseOffering **courseOfferings;

public:
    /**
     * Constructs a Course instance.
     * @param title The title of the course
     * @param courseCode The course code of the course
     * @param credits The number of credits the course gives when passed
     */
    Course(const string &title, const string &courseCode, int credits);

    /**
     * Destructs the Course instance.
     * Note that CourseOffering objects are owned by the relevant Course instances.
     */
    ~Course();

    /**
     * Compares this course against another.
     * @param other The course to compare against
     * @return An integer < 0 if the course code is lexicographically ordered before the other course's course code;
     *         0 if their values are equivalent; or
     *         > 0 if the course code is lexicographically ordered after the other course's course code.
     */
    int compareTo(const Course &other) const;

    /**
     * Adds an offering to the Course.
     * This function assumes the existing course offering does not exist.
     * `Course::hasOffering` should be called to check for duplicates before using this function.
     * @param semester The semester of the offering to add
     * @param year The year of the offering to add
     * @return The newly-created CourseOffering object.
     */
    CourseOffering* addOffering(Semester semester, int year);

    /**
     * Checks if a particular offering of the course exists.
     * @param semester The semester of the offering to check
     * @param year The year of the offering to check
     * @return True if it exists; false otherwise.
     */
    bool hasOffering(Semester semester, int year) const;

    /**
     * Gets an existing offering of the Course.
     * This function assumes the existing course offering exists.
     * `Course::hasOffering` should be called to check for existence before using this function.
     * @param semester The semester of the offering to get
     * @param year The year of the offering to get
     * @return The CourseOffering object asked for.
     */
    CourseOffering* getOffering(Semester semester, int year) const;

    // The following functions are implemented for you.

    /**
     * Prints the basic information of the course.
     */
    void printInfo() const;

    /**
     * Prints the basic information of the course and information of its offerings.
     */
    void printOfferings() const;
};

#endif
