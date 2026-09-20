#ifndef STUDENT_H
#define STUDENT_H

#include <string>

#include "Course.h"
using namespace std;

/**
 * A class representing a student.
 */
class Student {
private:
    /**
     * The name of the student.
     */
    string name;
    /**
     * The ID of the student. This value should be unique.
     */
    int id;
    /**
     * The year of study of the student.
     */
    int yearOfStudy;
    /**
     * The type of the student
     */
    StudentType studentType;
    /**
     * The region at which the student resides.
     */
    Region region;
    /**
     * The school the student belongs to.
     */
    School school;
    /**
     * The number of courses the student has taken.
     */
    int numTaken;
    /**
     * An array of CourseOfferings the student has taken.
     */
    const CourseOffering **coursesTaken;
    /**
     * The partner matched to the student, if any.
     */
    const Student *partner;
    
public:
    /**
     * Constructs a Student instance.
     * @param name The name of the student.
     * @param id The ID of the student
     * @param yearOfStudy The year of study of the student.
     * @param studentType The type of the student
     * @param region The location at which the student resides.
     * @param school The school the student belongs to.
     */
    Student(const string &name, int id, int yearOfStudy, StudentType studentType, Region region, School school);

    /**
     * Destructs a Student instance.
     */
    ~Student();

    /**
     * Sets/Removes a partner to the student.
     * @param partner The partner to set, or `nullptr`
     */
    void setPartner(const Student *partner);

    /**
     * Enrolls a student into a course. An offering of the course should be created if it does not exist.
     * @param course The course to enroll the student in
     * @param semester The semester to enroll the student in the course
     * @param year The year to enroll the student in the course
     * @param grade The grade assigned to the student.
     */
    Student& enrollCourse(Course &course, Semester semester, int year, const Grades &grade);

    /**
     * Calculates the partner score with another student.
     * The rules are as follows:
     *   - If both students are of the same year, increase the score by `SAME_YEAR`.
     *   - If both students are of the same student type, increase the score by `SAME_STUDENT_TYPE`.
     *   - If both students reside in same region, increase the score by `SAME_REGION`.
     *   - If both students are of the same school, increase the score by `SAME_SCHOOL`.
     *   - If both students have taken the same courses, for each course that both have taken:
     *      - Increase the score by `SAME_COURSE` if they are taking/took it in different semesters; otherwise
     *      - Increase the score by `SAME_COURSE` multiplied by `SAME_OFFERING_FACTOR`.
     * @param other The other student to compute the partner score with
     * @return The calculated score.
     */
    double calculateScore(const Student &other) const;

    // The following functions are implemented for you.

    /**
     * Gets the ID of the student.
     * @return The ID of the student.
     */
    int getId() const;

    /**
     * Gets the year of study of the student.
     * @return The year of study of the student.
     */
    int getYearOfStudy() const;

    /**
     * Gets the partner of the student, if any.
     * @return The partner of the student if any, nullptr otherwise.
     */
    const Student* getPartner() const;

    /**
     * Prints the basic information of the student.
     */
    void printInfo() const;

    /**
     * Prints a student's course history.
     */
    void printCourseHistory() const;
};


#endif
