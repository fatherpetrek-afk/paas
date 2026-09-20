#ifndef COURSE_OFFERING_H
#define COURSE_OFFERING_H

#include "Constants.h"
#include "Course.h"
using namespace std;

class Course;

/**
 * A class representing an offering of a Course.
 * A course can have multiple offerings, but each offering should be unique,
 * i.e. one course offering should be represented by only one CourseOffering instance.
 */
class CourseOffering {
private:
    /**
     * The course the offering is representing.
     */
    Course *course;
    /**
     * The semester the offering is in.
     */
    Semester semester;
    /**
     * The year the offering is in.
     */
    int year;
    /**
     * An array of student IDs, where each row represents the grade the student acquired.
     * This means IDs stored within studentGrades[A] acquired the A grade from this offering.
     */
    int *studentGrades[NUM_POSSIBLE_GRADES];
    /**
     * The lengths of each row of the studentGrades array.
     * This studentGrades[A] has gradeLengths[A] grades stored.
     */
    int gradeLengths[NUM_POSSIBLE_GRADES];

public:
    /**
     * Constructs an instance of a CourseOffering object.
     * @param course The course the offering represents
     * @param semester The semester of the offering
     * @param year The year of the offering
     */
    CourseOffering(Course *course, Semester semester, int year);

    /**
     * Destructs a CourseOffering instance.
     */
    ~CourseOffering();

    /**
     * Compares this course offering against another.
     * If the offerings belong to different courses, the value of `Course::compareTo` is returned.
     * Otherwise, the offerings are compared by time of occurrence.
     * @param other The course offering to compare against
     * @return The result of `Course::compareTo` of the offerings are of different courses; otherwise,
     *         an integer < 0 if the offering happens before the other;
     *         0 if they happen in the same semester; or
     *         > 0 if the offering happens after the other.
     */
    int compareTo(const CourseOffering &other) const;

    /**
     * Checks if two course offerings belong to the same course.
     * @param other The course offering to compare against
     * @return True if both course offerings belong to the same course; false otherwise.
     */
    bool sameCourse(const CourseOffering &other) const;

    /**
     * Checks if the offering happens in a given semester.
     * @param semester The semester name
     * @param year The year of the semester
     * @return True if it occurs in the given semester; false otherwise.
     */
    bool sameSemester(Semester semester, int year) const;

    /**
     * Assigns a new grade to a particular student for the course offering.
     * @param studentId The ID of the student to assign the grade to
     * @param grade The grade to be assigned
     * @return A reference to the CourseOffering object, convenient for chaining.
     */
    CourseOffering& assignGrade(int studentId, const Grades &grade);

    /**
     * Gets the grade of a student.
     * @param studentId The ID of the student
     * @return A floating-point representation of the student's grade, calculated via `gradeToOrdinal`, or 0 if the student is not found.
     */
    double getGrade(int studentId) const;

    // The following functions are implemented for you.

    /**
     * Prints basic information about the course offering.
     */
    void printInfo() const;

    /**
     * Prints detailed information about the course offering.
     */
    void printOffering() const;
};

#endif

